"""Configuration helpers for the Hermes Feishu plugin."""

from __future__ import annotations

from typing import Any

DEFAULT_BOT_NAME = "Hermes"

STATUS_LABELS = {
    "thinking": "思考中",
    "streaming": "生成中",
    "complete": "已完成",
    "error": "发送失败",
}

STATUS_TEMPLATES = {
    "thinking": "indigo",
    "streaming": "blue",
    "complete": "green",
    "error": "red",
}

STATUS_EMOJI = {
    "thinking": "🤔",
    "streaming": "⌨️",
    "complete": "✅",
    "error": "⚠️",
}


def bot_display_name(adapter: Any) -> str:
    for candidate in (
        getattr(adapter, "_bot_name", ""),
        getattr(adapter, "bot_name", ""),
        getattr(adapter, "name", ""),
        DEFAULT_BOT_NAME,
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return DEFAULT_BOT_NAME


def status_title(adapter: Any, phase: str) -> str:
    name = bot_display_name(adapter)
    label = STATUS_LABELS.get(phase, STATUS_LABELS["streaming"])
    emoji = STATUS_EMOJI.get(phase, STATUS_EMOJI["streaming"])
    return f"{emoji} {name} · {label}"
