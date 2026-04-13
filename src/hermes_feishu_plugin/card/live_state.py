"""Helpers for reading and shaping live Feishu card runtime state."""

from __future__ import annotations

import asyncio
from typing import Any

from ..channel.runtime_state import (
    get_chat_state,
    get_display_text,
    get_elapsed_seconds,
    get_fallback_tool_lines,
    get_heartbeat_status_text,
    get_last_flushed_text,
    get_tool_steps,
)
from .tool_display import fallback_steps_from_lines


def current_progress_text(adapter: Any, chat_id: str) -> str:
    """Return the best available live text for in-place progress refreshes."""
    display_text = get_display_text(adapter, chat_id)
    if display_text.strip():
        return display_text
    return get_last_flushed_text(adapter, chat_id)


def current_heartbeat_text(adapter: Any, chat_id: str) -> str:
    """Return the current lightweight heartbeat note."""
    return get_heartbeat_status_text(adapter, chat_id)


def visible_tool_steps(adapter: Any, chat_id: str) -> list[Any]:
    """Return structured tool steps, falling back to parsed plain lines."""
    steps = get_tool_steps(adapter, chat_id)
    if steps:
        return steps
    return fallback_steps_from_lines(get_fallback_tool_lines(adapter, chat_id))


def should_show_tool_use(adapter: Any, chat_id: str) -> bool:
    """Only render the tool panel after real tool activity exists."""
    return bool(visible_tool_steps(adapter, chat_id))


def elapsed_ms(adapter: Any, chat_id: str) -> int | None:
    """Return chat elapsed time in milliseconds."""
    seconds = get_elapsed_seconds(adapter, chat_id)
    if seconds is None:
        return None
    return int(seconds * 1000)


def get_card_update_lock(adapter: Any, chat_id: str) -> asyncio.Lock:
    """Return the serialized card-update lock for a chat."""
    state = get_chat_state(adapter, chat_id)
    if state.card_update_lock is None:
        state.card_update_lock = asyncio.Lock()
    return state.card_update_lock
