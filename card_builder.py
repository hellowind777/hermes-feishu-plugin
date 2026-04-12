"""Build Feishu cards closer to the official OpenClaw CardKit style."""

from __future__ import annotations

import json
from typing import Any

from .i18n import select_text, with_i18n
from .runtime_state import get_elapsed_seconds, get_tool_steps

STREAMING_ELEMENT_ID = "streaming_content"


def _extract_thinking_content(text: str) -> str:
    if not text:
        return ""
    result = ""
    last_index = 0
    in_thinking = False
    import re

    scan_re = re.compile(r"<\s*(\/?)\s*(?:think(?:ing)?|thought|antthinking)\s*>", re.IGNORECASE)
    for match in scan_re.finditer(text):
        idx = match.start()
        if in_thinking:
            result += text[last_index:idx]
        in_thinking = match.group(1) != "/"
        last_index = match.end()
    if in_thinking:
        result += text[last_index:]
    return result.strip()


def _strip_reasoning_tags(text: str) -> str:
    import re

    result = re.sub(
        r"<\s*(?:think(?:ing)?|thought|antthinking)\s*>[\s\S]*?<\s*\/\s*(?:think(?:ing)?|thought|antthinking)\s*>",
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
        r"<\s*\/\s*(?:think(?:ing)?|thought|antthinking)\s*>",
        "",
        result,
        flags=re.IGNORECASE,
    )
    return result.strip()


def split_reasoning_text(text: str) -> tuple[str, str]:
    """Split Hermes model output into reasoning and visible answer."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return "", ""
    if cleaned.startswith("Reasoning:\n") and len(cleaned) > len("Reasoning:\n"):
        reasoning = cleaned[len("Reasoning:\n") :].strip()
        return reasoning, ""
    reasoning = _extract_thinking_content(cleaned)
    answer = _strip_reasoning_tags(cleaned)
    if not reasoning:
        return "", cleaned
    return reasoning, answer


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remain = int(round(seconds % 60))
    return f"{minutes}m {remain}s"


def _summarize(text: str, *, fallback: str) -> str:
    plain = " ".join(str(text or "").split()).strip()
    if not plain:
        return fallback
    return plain[:120]


def _build_tool_title(tool_steps: list[str], *, elapsed: str, is_final: bool) -> tuple[str, str]:
    zh_parts = ["工具执行" if not is_final else "已执行工具"]
    en_parts = ["Tool use" if not is_final else "Tools used"]
    if tool_steps:
        zh_parts.append(f"{len(tool_steps)} 步")
        en_parts.append(f"{len(tool_steps)} step{'s' if len(tool_steps) != 1 else ''}")
    if elapsed:
        zh_parts.append(f"({elapsed})")
        en_parts.append(f"({elapsed})")
    return "🛠️ " + " · ".join(zh_parts), "🛠️ " + " · ".join(en_parts)


def _build_tool_panel(tool_steps: list[str], *, elapsed: str, is_final: bool) -> dict[str, Any]:
    zh_title, en_title = _build_tool_title(tool_steps, elapsed=elapsed, is_final=is_final)
    return {
        "tag": "collapsible_panel",
        "expanded": True,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": en_title,
                "i18n_content": {
                    "zh_cn": zh_title,
                    "en_us": en_title,
                },
                "text_color": "grey",
                "text_size": "notation",
            },
            "vertical_align": "center",
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
                "color": "grey",
                "size": "16px 16px",
            },
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": [
            {
                "tag": "markdown",
                "content": "\n".join(f"- {step}" for step in tool_steps[-8:]) or "- ...",
                "text_size": "notation",
            }
        ],
    }


def _build_live_stage_line(tool_steps: list[str]) -> dict[str, Any] | None:
    latest = _summarize(tool_steps[-1] if tool_steps else "", fallback="")
    if not latest:
        return None
    zh_text = f"🔄 当前阶段：{latest}"
    en_text = f"🔄 Current stage: {latest}"
    return {
        "tag": "markdown",
        **with_i18n("content", zh_text, en_text),
        "text_size": "notation",
    }


def _build_pending_tool_panel() -> dict[str, Any]:
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🛠️ Tool use pending",
                "i18n_content": {
                    "zh_cn": "🛠️ 等待工具执行",
                    "en_us": "🛠️ Tool use pending",
                },
                "text_color": "grey",
                "text_size": "notation",
            },
            "vertical_align": "center",
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
                "color": "grey",
                "size": "16px 16px",
            },
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": [
            {
                "tag": "markdown",
                **with_i18n(
                    "content",
                    "工具尚未启动；一旦开始调用，这里会显示工具名和步骤预览。",
                    "No tool has started yet. Tool names and step previews will appear here once execution begins.",
                ),
                "text_size": "notation",
            }
        ],
    }


def _build_reasoning_panel(reasoning: str, *, is_final: bool, elapsed: str) -> dict[str, Any]:
    if not is_final:
        return {
            "tag": "markdown",
            **with_i18n(
                "content",
                f"💭 **思考中...**\n\n{reasoning}",
                f"💭 **Thinking...**\n\n{reasoning}",
            ),
            "text_size": "notation",
        }
    zh_label = f"💭 思考（{elapsed}）" if elapsed else "💭 思考"
    en_label = f"💭 Thought ({elapsed})" if elapsed else "💭 Thought"
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "markdown",
                "content": en_label,
                "i18n_content": {
                    "zh_cn": zh_label,
                    "en_us": en_label,
                },
            },
            "vertical_align": "center",
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
                "size": "16px 16px",
            },
            "icon_position": "follow_text",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "8px",
        "padding": "8px 8px 8px 8px",
        "elements": [
            {
                "tag": "markdown",
                "content": reasoning,
                "text_size": "notation",
            }
        ],
    }


def _build_footer(*, is_final: bool, elapsed: str, has_tools: bool) -> dict[str, Any] | None:
    zh_parts: list[str] = []
    en_parts: list[str] = []
    zh_parts.append("已完成" if is_final else "处理中")
    en_parts.append("Completed" if is_final else "Processing")
    if elapsed:
        zh_parts.append(elapsed)
        en_parts.append(elapsed)
    if has_tools:
        zh_parts.append("单消息流式更新")
        en_parts.append("Single-message streaming")
    if not zh_parts:
        return None
    return {
        "tag": "markdown",
        **with_i18n("content", " · ".join(zh_parts), " · ".join(en_parts)),
        "text_size": "notation",
    }


def build_streaming_card(adapter: Any, chat_id: str, text: str, *, is_final: bool) -> str:
    """Return a Feishu interactive card JSON string."""
    reasoning, answer = split_reasoning_text(text)
    tool_steps = get_tool_steps(adapter, chat_id)
    elapsed = _format_elapsed(get_elapsed_seconds(adapter, chat_id))
    elements: list[dict[str, Any]] = []
    visible_answer = answer.strip()

    if tool_steps:
        elements.append(_build_tool_panel(tool_steps, elapsed=elapsed, is_final=is_final))
        if not is_final:
            live_stage_line = _build_live_stage_line(tool_steps)
            if live_stage_line:
                elements.append(live_stage_line)
    elif not is_final and not reasoning and not visible_answer:
        elements.append(_build_pending_tool_panel())

    if reasoning:
        elements.append(_build_reasoning_panel(reasoning, is_final=is_final, elapsed=elapsed))

    if visible_answer:
        elements.append(
            {
                "tag": "markdown",
                "content": visible_answer,
                "text_align": "left",
                "text_size": "normal_v2",
                "margin": "0px 0px 0px 0px",
                "element_id": STREAMING_ELEMENT_ID,
            }
        )
    elif not is_final:
        elements.append(
            {
                "tag": "markdown",
                "content": "",
                "text_align": "left",
                "text_size": "normal_v2",
                "margin": "0px 0px 0px 0px",
                "element_id": STREAMING_ELEMENT_ID,
            }
        )
        elements.append(
            {
                "tag": "markdown",
                **with_i18n("content", "⌨️ 处理中...", "⌨️ Processing..."),
                "text_size": "notation",
                "element_id": "loading_icon",
            }
        )
    elif not elements:
        elements.append(
            {
                "tag": "markdown",
                "content": "已完成。" if is_final else "思考中...",
            }
        )

    footer = _build_footer(
        is_final=is_final,
        elapsed=elapsed,
        has_tools=bool(tool_steps),
    )
    if footer:
        elements.append(footer)

    card = {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
            "streaming_mode": not is_final,
            "locales": ["zh_cn", "en_us"],
            "summary": {
                "content": _summarize(
                    visible_answer or reasoning,
                    fallback=select_text("处理中", "Processing") if not is_final else select_text("已完成", "Completed"),
                )
            },
        },
        "body": {"elements": elements},
    }
    return json.dumps(card, ensure_ascii=False)
