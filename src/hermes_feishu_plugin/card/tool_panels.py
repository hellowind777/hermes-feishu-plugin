"""Tool-use panel builders for Feishu cards."""

from __future__ import annotations

import re
from typing import Any

from ..core.i18n import select_text
from .models import ToolDisplayStep

TOOL_USE_STEP_CONTENT_INDENT = "0px 0px 0px 22px"

_TOOL_TITLE_ZH = {
    "Tool": "工具",
    "Load skill": "加载技能",
    "Read": "读取文件",
    "Edit": "编辑文件",
    "Search web": "搜索网页",
    "Fetch web page": "抓取网页",
    "Search text": "搜索文本",
    "Search files": "搜索文件",
    "Run command": "执行命令",
    "Browser": "浏览器",
    "Run sub-agent": "运行子代理",
}


def build_streaming_tool_use_pending_panel() -> dict[str, Any]:
    """Build the collapsed pending tool-use panel."""
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": _collapsible_header(
            zh="🛠️ 等待工具执行",
            en="🛠️ Tool use pending",
            icon_position="right",
        ),
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": [],
    }


def build_streaming_tool_use_active_panel(
    steps: list[ToolDisplayStep],
    *,
    tool_elapsed_ms: int | None,
) -> dict[str, Any]:
    """Build the expanded pre-answer tool-use panel."""
    zh_parts = ["工具执行"]
    en_parts = ["Tool use"]
    if steps:
        zh_parts.append(f"{len(steps)} 步")
        en_parts.append(f"{len(steps)} step{'s' if len(steps) != 1 else ''}")
    if tool_elapsed_ms:
        duration = format_elapsed(tool_elapsed_ms)
        zh_parts.append(f"({duration})")
        en_parts.append(f"({duration})")

    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": _collapsible_header(
            zh=f"🛠️ {' · '.join(zh_parts)}",
            en=f"🛠️ {' · '.join(en_parts)}",
            icon_position="right",
        ),
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": _build_tool_step_elements(steps[-12:]),
    }


def build_tool_use_panel(
    steps: list[ToolDisplayStep],
    *,
    tool_elapsed_ms: int | None = None,
    expanded: bool = False,
) -> dict[str, Any]:
    """Build the final tool-use collapsible panel."""
    duration = format_elapsed(tool_elapsed_ms) if tool_elapsed_ms else ""
    zh_title = f"🛠️ 工具执行{f' · {duration}' if duration else ''}"
    en_title = f"🛠️ Tool use{f' · {duration}' if duration else ''}"
    if steps:
        zh_title += f" · 查看 {len(steps)} 个步骤"
        en_title += f" · Show {len(steps)} step{'s' if len(steps) != 1 else ''}"

    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "header": _collapsible_header(zh=zh_title, en=en_title, icon_position="right"),
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": _build_tool_step_elements(steps[-12:]) or [_build_tool_placeholder()],
    }


def format_elapsed(ms: int | float | None) -> str:
    """Format milliseconds into a short human-readable duration."""
    if ms is None:
        return ""
    seconds = float(ms) / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {round(seconds % 60)}s"


def _collapsible_header(zh: str, en: str, *, icon_position: str) -> dict[str, Any]:
    return {
        "title": {
            "tag": "plain_text",
            "content": select_text(zh, en),
            "i18n_content": {"zh_cn": zh, "en_us": en},
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
        "icon_position": icon_position,
        "icon_expanded_angle": -180,
    }


def _build_tool_step_elements(steps: list[ToolDisplayStep]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for step in steps:
        elements.append(_build_tool_step_title(step))
        if step.detail:
            elements.append(_build_tool_step_detail(step.detail))
        if step.error_block:
            elements.append(_build_tool_block("错误", "Error", step.error_block))
        elif step.result_block:
            elements.append(_build_tool_block("结果", "Result", step.result_block))
    return elements


def _build_tool_step_title(step: ToolDisplayStep) -> dict[str, Any]:
    status = _tool_status(step.status)
    title = _localize_tool_title(step.title)
    if step.duration_ms is not None:
        title = f"{title} ({format_elapsed(step.duration_ms)})"
    return {
        "tag": "div",
        "icon": {"tag": "standard_icon", "token": step.icon_token, "color": "grey"},
        "text": {
            "tag": "lark_md",
            "content": f"**{_escape_tool_markdown(title)}** · <font color='{status['color']}'>{status['label']}</font>",
            "text_size": "notation",
        },
    }


def _build_tool_step_detail(detail: str) -> dict[str, Any]:
    return {
        "tag": "div",
        "margin": TOOL_USE_STEP_CONTENT_INDENT,
        "text": {
            "tag": "plain_text",
            "content": detail,
            "text_color": "grey",
            "text_size": "notation",
        },
    }


def _build_tool_block(zh_label: str, en_label: str, block: Any) -> dict[str, Any]:
    label = select_text(zh_label, en_label)
    fence = _code_fence(block.content)
    content = f"**{label}**\n{fence}{block.language}\n{block.content}\n{fence}"
    return {
        "tag": "div",
        "margin": TOOL_USE_STEP_CONTENT_INDENT,
        "text": {"tag": "lark_md", "content": content, "text_size": "notation"},
    }


def _build_tool_placeholder() -> dict[str, Any]:
    zh = "暂无工具步骤"
    en = "No tool steps available"
    return {
        "tag": "div",
        "text": {
            "tag": "plain_text",
            "content": select_text(zh, en),
            "i18n_content": {"zh_cn": zh, "en_us": en},
            "text_color": "grey",
            "text_size": "notation",
        },
    }


def _tool_status(status: str) -> dict[str, str]:
    if status == "running":
        return {"label": select_text("执行中", "Running"), "color": "turquoise"}
    if status == "error":
        return {"label": select_text("失败", "Failed"), "color": "red"}
    return {"label": select_text("成功", "Succeeded"), "color": "green"}


def _localize_tool_title(title: str) -> str:
    text = str(title or "").strip()
    if not text:
        return select_text("工具", "Tool")
    return select_text(_TOOL_TITLE_ZH.get(text, text), text)


def _code_fence(text: str) -> str:
    runs = re.findall(r"`+", text or "")
    longest = max((len(run) for run in runs), default=2)
    return "`" * max(3, longest + 1)


def _escape_tool_markdown(text: str) -> str:
    return re.sub(r"([`*_{}\[\]<>])", r"\\\1", str(text or ""))
