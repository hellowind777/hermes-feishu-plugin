"""Build Feishu cards aligned with OpenClaw's CardKit interaction style."""

from __future__ import annotations

import re
from typing import Any

from ..core.i18n import select_text, with_i18n
from .errors import sanitize_text_segments_for_card
from .models import ToolDisplayStep
from .tool_panels import (
    build_streaming_tool_use_active_panel,
    build_streaming_tool_use_pending_panel,
    build_tool_use_panel,
    format_elapsed,
)

STREAMING_ELEMENT_ID = "streaming_content"
REASONING_ELEMENT_ID = "reasoning_content"
LOADING_ICON_KEY = "img_v3_02vb_496bec09-4b43-4773-ad6b-0cdd103cd2bg"
_REASONING_PREFIX = "Reasoning:\n"


def split_reasoning_text(text: str | None) -> tuple[str, str]:
    """Split model output into reasoning and visible answer."""
    if not isinstance(text, str) or not text.strip():
        return "", ""

    stripped = text.strip()
    if stripped.startswith(_REASONING_PREFIX) and len(stripped) > len(_REASONING_PREFIX):
        return _clean_reasoning_prefix(stripped), ""

    reasoning = _extract_thinking_content(text)
    answer = strip_reasoning_tags(text)
    if not reasoning and answer == text:
        return "", text
    return reasoning, answer


def strip_reasoning_tags(text: str) -> str:
    """Strip XML-style reasoning tags from visible answer text."""
    result = re.sub(
        r"<\s*(?:think(?:ing)?|thought|antthinking)\s*>[\s\S]*?<\s*/\s*(?:think(?:ing)?|thought|antthinking)\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"<\s*(?:think(?:ing)?|thought|antthinking)\s*>[\s\S]*$",
        "",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"<\s*/\s*(?:think(?:ing)?|thought|antthinking)\s*>",
        "",
        result,
        flags=re.IGNORECASE,
    )
    return result.strip()


def build_streaming_pre_answer_card(
    *,
    text: str = "",
    tool_steps: list[ToolDisplayStep] | None = None,
    tool_elapsed_ms: int | None = None,
    status_text: str = "",
    show_tool_use: bool = True,
) -> dict[str, Any]:
    """Build the official-style CardKit 2.0 pre-answer streaming card."""
    steps = list(tool_steps or [])
    elements: list[dict[str, Any]] = []

    if show_tool_use:
        elements.append(
            build_streaming_tool_use_active_panel(steps, tool_elapsed_ms=tool_elapsed_ms)
            if steps
            else build_streaming_tool_use_pending_panel()
        )

    elements.append(
        {
            "tag": "markdown",
            "content": _optimize_markdown_style(text or status_text),
            "text_align": "left",
            "text_size": "normal_v2",
            "margin": "0px 0px 0px 0px",
            "element_id": STREAMING_ELEMENT_ID,
        }
    )
    elements.append(
        {
            "tag": "markdown",
            "content": " ",
            "icon": {
                "tag": "custom_icon",
                "img_key": LOADING_ICON_KEY,
                "size": "16px 16px",
            },
            "element_id": "loading_icon",
        }
    )

    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "locales": ["zh_cn", "en_us"],
            "summary": {
                "content": select_text("处理中...", "Processing..."),
                "i18n_content": {"zh_cn": "处理中...", "en_us": "Processing..."},
            },
        },
        "body": {"elements": elements},
    }


def build_streaming_patch_card(
    *,
    text: str = "",
    tool_steps: list[ToolDisplayStep] | None = None,
    status_text: str = "",
    show_tool_use: bool = True,
) -> dict[str, Any]:
    """Build the IM patch fallback streaming card."""
    reasoning, answer = split_reasoning_text(text)
    elements: list[dict[str, Any]] = []
    steps = list(tool_steps or [])

    if show_tool_use:
        elements.append(build_tool_use_panel(steps, expanded=False) if steps else build_streaming_tool_use_pending_panel())

    if reasoning and not answer:
        elements.append(
            {
                "tag": "markdown",
                **with_i18n(
                    "content",
                    f"💭 **思考中...**\n\n{reasoning}",
                    f"💭 **Thinking...**\n\n{reasoning}",
                ),
                "text_size": "notation",
            }
        )
    elif answer:
        elements.append({"tag": "markdown", "content": _optimize_markdown_style(answer)})
    elif status_text.strip():
        elements.append({"tag": "markdown", "content": _optimize_markdown_style(status_text)})

    return {
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
            "locales": ["zh_cn", "en_us"],
        },
        "elements": elements,
    }


def build_complete_card(
    *,
    text: str,
    tool_steps: list[ToolDisplayStep] | None = None,
    tool_elapsed_ms: int | None = None,
    elapsed_ms: int | None = None,
    is_error: bool = False,
    is_aborted: bool = False,
    show_tool_use: bool = True,
) -> dict[str, Any]:
    """Build the final non-streaming Feishu card."""
    reasoning, answer = split_reasoning_text(text)
    sanitized_reasoning, sanitized_answer = sanitize_text_segments_for_card([reasoning, answer])
    elements: list[dict[str, Any]] = []

    if show_tool_use:
        elements.append(build_tool_use_panel(list(tool_steps or []), tool_elapsed_ms=tool_elapsed_ms))

    if sanitized_reasoning:
        elements.append(_build_reasoning_panel(sanitized_reasoning, elapsed_ms=elapsed_ms))

    elements.append({"tag": "markdown", "content": _optimize_markdown_style(sanitized_answer or text or select_text("已完成。", "Done."))})

    footer = _build_footer(
        elapsed_ms=elapsed_ms,
        is_error=is_error,
        is_aborted=is_aborted,
    )
    if footer:
        elements.append(footer)

    summary_text = _plain_summary(sanitized_answer or text)
    summary = {"content": summary_text[:120]} if summary_text else None
    return {
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
            "locales": ["zh_cn", "en_us"],
            **({"summary": summary} if summary else {}),
        },
        "elements": elements,
    }


def to_cardkit2(card: dict[str, Any]) -> dict[str, Any]:
    """Convert old-style interactive card to CardKit 2.0 format."""
    if card.get("schema") == "2.0":
        return card
    result: dict[str, Any] = {
        "schema": "2.0",
        "config": card.get("config", {}),
        "body": {"elements": card.get("elements", [])},
    }
    if "header" in card:
        result["header"] = card["header"]
    return result


def _extract_thinking_content(text: str) -> str:
    scan_re = re.compile(r"<\s*(/?)\s*(?:think(?:ing)?|thought|antthinking)\s*>", re.IGNORECASE)
    result = ""
    last_index = 0
    in_thinking = False
    for match in scan_re.finditer(text):
        if in_thinking:
            result += text[last_index : match.start()]
        in_thinking = match.group(1) != "/"
        last_index = match.end()
    if in_thinking:
        result += text[last_index:]
    return result.strip()


def _clean_reasoning_prefix(text: str) -> str:
    cleaned = re.sub(r"^Reasoning:\s*", "", text, flags=re.IGNORECASE)
    return "\n".join(re.sub(r"^_(.+)_$", r"\1", line) for line in cleaned.splitlines()).strip()


def _build_reasoning_panel(reasoning_text: str, *, elapsed_ms: int | None) -> dict[str, Any]:
    label = format_elapsed(elapsed_ms) if elapsed_ms else ""
    zh_label = f"💭 思考了 {label}" if label else "💭 思考"
    en_label = f"💭 Thought for {label}" if label else "💭 Thought"
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "markdown",
                "content": select_text(zh_label, en_label),
                "i18n_content": {"zh_cn": zh_label, "en_us": en_label},
            },
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
            "icon_position": "follow_text",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "8px",
        "padding": "8px 8px 8px 8px",
        "elements": [{"tag": "markdown", "content": reasoning_text, "text_size": "notation"}],
    }


def _build_footer(*, elapsed_ms: int | None, is_error: bool, is_aborted: bool) -> dict[str, Any]:
    zh_parts = ["出错" if is_error else "已停止" if is_aborted else "已完成"]
    en_parts = ["Error" if is_error else "Stopped" if is_aborted else "Completed"]
    if elapsed_ms is not None:
        duration = format_elapsed(elapsed_ms)
        zh_parts.append(f"耗时 {duration}")
        en_parts.append(f"Elapsed {duration}")
    zh_content = " · ".join(zh_parts)
    en_content = " · ".join(en_parts)
    if is_error:
        zh_content = f"<font color='red'>{zh_content}</font>"
        en_content = f"<font color='red'>{en_content}</font>"
    return {
        "tag": "markdown",
        "content": select_text(zh_content, en_content),
        "i18n_content": {"zh_cn": zh_content, "en_us": en_content},
        "text_size": "notation",
    }


def _optimize_markdown_style(text: str) -> str:
    return str(text or "").strip()


def _plain_summary(text: str) -> str:
    return re.sub(r"[*_`#>\[\]()~]", "", str(text or "")).strip()
