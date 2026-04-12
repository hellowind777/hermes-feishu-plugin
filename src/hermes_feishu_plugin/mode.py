"""Reply-mode helpers aligned with the OpenClaw Feishu defaults."""

from __future__ import annotations

import os
from typing import Any

from .runtime_state import get_chat_type

_VALID_REPLY_MODES = {"auto", "static", "streaming"}


def resolve_reply_mode(adapter: Any, chat_id: str) -> str:
    """Resolve effective reply mode for a Feishu chat."""
    configured = str(
        getattr(adapter, "_hermes_feishu_reply_mode", "")
        or os.getenv("HERMES_FEISHU_REPLY_MODE", "auto")
    ).strip().lower()
    mode = configured if configured in _VALID_REPLY_MODES else "auto"
    if mode != "auto":
        return mode
    return "static" if get_chat_type(adapter, chat_id) == "group" else "streaming"


def should_stream(adapter: Any, chat_id: str) -> bool:
    """Return True when the chat should use streaming cards."""
    return resolve_reply_mode(adapter, chat_id) == "streaming"
