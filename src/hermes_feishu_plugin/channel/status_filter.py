"""Shared filtering rules for Hermes Feishu status-only messages."""

from __future__ import annotations

import re

_RETRY_RE = re.compile(r"^⏳\s+Retrying in .+\(attempt \d+/\d+\)\.\.\.$")
_STILL_WORKING_RE = re.compile(r"^⏳\s+Still working\.\.\. \(\d+\s+min elapsed(?:\s+—\s+.*)?\)$")
_FALLBACK_RE = re.compile(r"^(↪️|↪|🔄)?\s*Primary model failed\s+—\s+switching to fallback:", re.I)
_RATE_LIMIT_FALLBACK_RE = re.compile(r"^(⚠️|⚠)?\s*Rate limited\s+—\s+switching to fallback provider", re.I)
_EMPTY_FALLBACK_RE = re.compile(r"^(⚠️|⚠)?\s*Empty/malformed response\s+—\s+switching to fallback", re.I)
_NON_RETRYABLE_FALLBACK_RE = re.compile(r"^(⚠️|⚠)?\s*Non-retryable error.*trying fallback", re.I)
_MAX_RETRIES_RE = re.compile(r"^(⚠️|⚠)\s+Max retries \(\d+\) exhausted\s+—\s+trying fallback")
_INVALID_RETRIES_RE = re.compile(r"^(⚠️|⚠)\s+Max retries \(\d+\) for invalid responses\s+—\s+trying fallback")
_TOOL_PROGRESS_LINE_RE = re.compile(r"^[^\w\s]{1,4}\s+[A-Za-z0-9_.-]+(?:\([^)]*\))?(?::.*|\.\.\.)?$")


def _looks_like_tool_progress_line(line: str) -> bool:
    cleaned = str(line or "").strip()
    if not cleaned:
        return False
    if is_context_pressure_message(cleaned):
        return False
    if is_model_switch_status_message(cleaned):
        return False
    if _RETRY_RE.match(cleaned) or _STILL_WORKING_RE.match(cleaned) or _MAX_RETRIES_RE.match(cleaned):
        return False
    if cleaned.startswith("[tool]") or cleaned.startswith("[done]"):
        return True
    return bool(_TOOL_PROGRESS_LINE_RE.match(cleaned))


def is_tool_progress_block(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    if all(_looks_like_tool_progress_line(line) for line in lines):
        return True
    return bool(lines) and _looks_like_tool_progress_line(lines[0])


def parse_tool_progress_lines(text: str) -> list[str]:
    """Extract readable tool-progress lines from Hermes status text."""
    parsed: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if is_context_pressure_message(line):
            continue
        if _RETRY_RE.match(line) or _STILL_WORKING_RE.match(line) or is_model_switch_status_message(line) or _MAX_RETRIES_RE.match(line):
            continue
        if line.startswith("[tool]"):
            parsed.append(line[len("[tool]") :].strip())
            continue
        if line.startswith("[done]"):
            parsed.append(line[len("[done]") :].strip())
            continue
        if _TOOL_PROGRESS_LINE_RE.match(line):
            parsed.append(line)
            continue
        if parsed:
            parsed[-1] = f"{parsed[-1]} — {line}"
    return [line for line in parsed if line]


def is_context_pressure_message(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False

    first_line = cleaned.splitlines()[0].strip()
    return (
        (first_line.startswith("⚠️ Context:") or first_line.startswith("Context:"))
        and "to compaction" in cleaned
        and "Context compaction approaching" in cleaned
    )


def is_model_switch_status_message(text: str) -> bool:
    """Return True for provider fallback and model-switch lifecycle messages."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return any(
        pattern.match(cleaned)
        for pattern in (
            _FALLBACK_RE,
            _RATE_LIMIT_FALLBACK_RE,
            _EMPTY_FALLBACK_RE,
            _NON_RETRYABLE_FALLBACK_RE,
            _MAX_RETRIES_RE,
            _INVALID_RETRIES_RE,
        )
    )


def should_suppress_status_message(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if _RETRY_RE.match(cleaned):
        return True
    if _STILL_WORKING_RE.match(cleaned):
        return True
    if is_model_switch_status_message(cleaned):
        return True
    if is_context_pressure_message(cleaned):
        return True
    if is_tool_progress_block(cleaned):
        return True
    return False
