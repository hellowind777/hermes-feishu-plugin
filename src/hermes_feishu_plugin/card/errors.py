"""CardKit error handling helpers aligned with OpenClaw semantics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

CARD_RATE_LIMITED = 230020
CARD_CONTENT_FAILED = 230099
CARD_CONTENT_ELEMENT_LIMIT = 11310
FEISHU_CARD_TABLE_LIMIT = 3


class CardKitApiError(RuntimeError):
    """Raised when CardKit returned a business-level failure."""

    def __init__(self, *, api: str, code: int, msg: str, context: str) -> None:
        super().__init__(f"cardkit {api} failed: code={code}, msg={msg}, {context}")
        self.api = api
        self.code = code
        self.msg = msg
        self.context = context


@dataclass(frozen=True, slots=True)
class MarkdownTableMatch:
    """Markdown table match outside fenced code blocks."""

    index: int
    length: int
    raw: str


def extract_lark_api_code(err: Any) -> int | None:
    """Best-effort extract a Lark error code from response/exception objects."""
    if err is None:
        return None

    for candidate in (
        getattr(err, "code", None),
        getattr(getattr(err, "data", None), "code", None),
        getattr(getattr(getattr(err, "response", None), "data", None), "code", None),
    ):
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def extract_sub_code(msg: str) -> int | None:
    """Extract nested ErrCode from Feishu extended msg strings."""
    match = re.search(r"ErrCode:\s*(\d+)", str(msg or ""))
    if not match:
        return None
    return int(match.group(1))


def parse_card_api_error(err: Any) -> tuple[int, int | None, str] | None:
    """Return ``(code, sub_code, message)`` or ``None`` when unavailable."""
    code = extract_lark_api_code(err)
    if code is None:
        return None

    msg = ""
    for candidate in (
        getattr(err, "msg", None),
        getattr(getattr(getattr(err, "response", None), "data", None), "msg", None),
        getattr(err, "message", None),
        str(err) if err is not None else "",
    ):
        if isinstance(candidate, str) and candidate.strip():
            msg = candidate.strip()
            break

    return code, extract_sub_code(msg), msg


def is_card_rate_limit_error(err: Any) -> bool:
    """Return ``True`` for Feishu card rate limit errors."""
    parsed = parse_card_api_error(err)
    return bool(parsed and parsed[0] == CARD_RATE_LIMITED)


def is_card_table_limit_error(err: Any) -> bool:
    """Return ``True`` when Feishu rejected the card for table over-limit."""
    parsed = parse_card_api_error(err)
    if not parsed:
        return False
    code, sub_code, message = parsed
    return (
        code == CARD_CONTENT_FAILED
        and sub_code == CARD_CONTENT_ELEMENT_LIMIT
        and "table number over limit" in message.lower()
    )


def find_markdown_tables_outside_code_blocks(text: str) -> list[MarkdownTableMatch]:
    """Collect markdown tables that Feishu would render as card tables."""
    source = str(text or "")
    code_ranges: list[tuple[int, int]] = []
    for match in re.finditer(r"```[\s\S]*?```", source):
        code_ranges.append((match.start(), match.end()))

    def in_code_block(index: int) -> bool:
        return any(start <= index < end for start, end in code_ranges)

    matches: list[MarkdownTableMatch] = []
    table_re = re.compile(r"\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|$)")
    for match in table_re.finditer(source):
        if in_code_block(match.start()):
            continue
        matches.append(
            MarkdownTableMatch(
                index=match.start(),
                length=match.end() - match.start(),
                raw=match.group(0),
            )
        )
    return matches


def sanitize_text_segments_for_card(
    texts: list[str] | tuple[str, ...],
    table_limit: int = FEISHU_CARD_TABLE_LIMIT,
) -> list[str]:
    """Share a single markdown-table budget across multiple card text segments."""
    remaining = max(0, table_limit)
    sanitized: list[str] = []

    for text in texts:
        matches = find_markdown_tables_outside_code_blocks(text)
        if len(matches) <= remaining:
            remaining -= len(matches)
            sanitized.append(text)
            continue
        sanitized.append(_wrap_tables_beyond_limit(text, matches, remaining))
        remaining = 0

    return sanitized


def _wrap_tables_beyond_limit(
    text: str,
    matches: list[MarkdownTableMatch],
    keep_count: int,
) -> str:
    result = text
    for match in reversed(matches[keep_count:]):
        replacement = f"```\n{match.raw}\n```"
        result = result[: match.index] + replacement + result[match.index + match.length :]
    return result
