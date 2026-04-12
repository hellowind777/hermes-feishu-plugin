"""Per-chat runtime state for the Hermes Feishu plugin."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any

_CHAT_STATE_ATTR = "_hermes_feishu_chat_state"
_CHAT_RUNTIME_REGISTRY: dict[str, dict[str, Any]] = {}


@dataclass
class ChatRuntimeState:
    """Mutable chat-scoped state used by Feishu runtime patches."""

    generation: int = 0
    reply_to_message_id: str = ""
    chat_type: str = "dm"
    started_at: float = 0.0
    card_message_id: str = ""
    last_card_update_at: float = 0.0
    display_text: str = ""
    tool_steps: list[str] = field(default_factory=list)
    heartbeat_task: Any = None


def _normalize_chat_type(chat_type: str) -> str:
    normalized = str(chat_type or "").strip().lower()
    if normalized in {"group", "forum", "channel", "topic", "thread"}:
        return "group"
    return "dm"


def _get_state_map(adapter: Any) -> dict[str, ChatRuntimeState]:
    state_map = getattr(adapter, _CHAT_STATE_ATTR, None)
    if not isinstance(state_map, dict):
        state_map = {}
        setattr(adapter, _CHAT_STATE_ATTR, state_map)
    return state_map


def get_chat_state(adapter: Any, chat_id: str) -> ChatRuntimeState:
    """Return the runtime state for a chat, creating it if needed."""
    state_map = _get_state_map(adapter)
    key = str(chat_id or "").strip()
    state = state_map.get(key)
    if isinstance(state, ChatRuntimeState):
        return state
    state = ChatRuntimeState()
    state_map[key] = state
    return state


def reset_chat_state(adapter: Any, chat_id: str, *, reply_to_message_id: str = "", chat_type: str = "dm") -> ChatRuntimeState:
    """Reset chat state for a new inbound request."""
    key = str(chat_id or "").strip()
    previous = _get_state_map(adapter).get(key)
    previous_generation = previous.generation if isinstance(previous, ChatRuntimeState) else 0
    previous_task = previous.heartbeat_task if isinstance(previous, ChatRuntimeState) else None
    if previous_task and hasattr(previous_task, "cancel"):
        try:
            previous_task.cancel()
        except Exception:
            pass
    state = ChatRuntimeState(
        generation=previous_generation + 1,
        reply_to_message_id=str(reply_to_message_id or "").strip(),
        chat_type=_normalize_chat_type(chat_type),
        started_at=time.monotonic(),
    )
    _get_state_map(adapter)[key] = state
    return state


def remember_inbound_message(adapter: Any, chat_id: str, message_id: str, chat_type: str) -> ChatRuntimeState:
    """Create fresh per-chat state from the latest inbound message."""
    state = reset_chat_state(
        adapter,
        chat_id,
        reply_to_message_id=message_id,
        chat_type=chat_type,
    )
    register_chat_runtime(adapter, chat_id)
    return state


def remember_reply_target(adapter: Any, chat_id: str, message_id: str) -> None:
    """Persist the latest reply target for a chat."""
    state = get_chat_state(adapter, chat_id)
    state.reply_to_message_id = str(message_id or "").strip()


def remember_card_message(adapter: Any, chat_id: str, message_id: str) -> None:
    """Persist the active streaming-card message id for a chat."""
    state = get_chat_state(adapter, chat_id)
    state.card_message_id = str(message_id or "").strip()
    state.last_card_update_at = time.monotonic()


def get_card_message_id(adapter: Any, chat_id: str) -> str:
    """Return the active streaming-card message id for a chat."""
    return get_chat_state(adapter, chat_id).card_message_id.strip()


def get_generation(adapter: Any, chat_id: str) -> int:
    """Return the current chat-state generation."""
    return int(get_chat_state(adapter, chat_id).generation)


def get_last_card_update_at(adapter: Any, chat_id: str) -> float:
    """Return last card update timestamp for a chat."""
    return float(get_chat_state(adapter, chat_id).last_card_update_at or 0.0)


def remember_display_text(adapter: Any, chat_id: str, text: str) -> None:
    """Persist the latest visible streamed text for a chat."""
    state = get_chat_state(adapter, chat_id)
    state.display_text = str(text or "")


def get_display_text(adapter: Any, chat_id: str) -> str:
    """Return the latest visible streamed text for a chat."""
    return get_chat_state(adapter, chat_id).display_text


def remember_tool_steps(adapter: Any, chat_id: str, tool_steps: list[str]) -> None:
    """Persist the latest tool-progress lines for a chat."""
    state = get_chat_state(adapter, chat_id)
    state.tool_steps = [str(step).strip() for step in tool_steps if str(step).strip()]


def get_tool_steps(adapter: Any, chat_id: str) -> list[str]:
    """Return the latest tool-progress lines for a chat."""
    return list(get_chat_state(adapter, chat_id).tool_steps)


def get_reply_target(adapter: Any, chat_id: str) -> str:
    """Return the latest reply target for a chat."""
    return get_chat_state(adapter, chat_id).reply_to_message_id.strip()


def get_chat_type(adapter: Any, chat_id: str) -> str:
    """Return normalized chat type for a chat."""
    return get_chat_state(adapter, chat_id).chat_type


def get_elapsed_seconds(adapter: Any, chat_id: str) -> float | None:
    """Return elapsed processing time for a chat."""
    started_at = get_chat_state(adapter, chat_id).started_at
    if started_at <= 0:
        return None
    return max(0.0, time.monotonic() - started_at)


def get_heartbeat_task(adapter: Any, chat_id: str) -> Any:
    """Return the active heartbeat task for a chat, if any."""
    return get_chat_state(adapter, chat_id).heartbeat_task


def set_heartbeat_task(adapter: Any, chat_id: str, task: Any) -> None:
    """Persist the active heartbeat task for a chat."""
    get_chat_state(adapter, chat_id).heartbeat_task = task


def clear_heartbeat_task(adapter: Any, chat_id: str, task: Any | None = None) -> None:
    """Clear the active heartbeat task when it matches the expected one."""
    state = get_chat_state(adapter, chat_id)
    if task is not None and state.heartbeat_task is not task:
        return
    state.heartbeat_task = None


def register_chat_runtime(adapter: Any, chat_id: str, *, loop: Any | None = None) -> None:
    """Register the active adapter + loop for direct card updates."""
    key = str(chat_id or "").strip()
    if not key:
        return
    runtime_loop = loop
    if runtime_loop is None:
        try:
            runtime_loop = asyncio.get_running_loop()
        except RuntimeError:
            runtime_loop = None
    _CHAT_RUNTIME_REGISTRY[key] = {
        "adapter": adapter,
        "loop": runtime_loop,
    }


def get_registered_adapter(chat_id: str) -> Any | None:
    """Return the registered adapter for a chat id."""
    key = str(chat_id or "").strip()
    entry = _CHAT_RUNTIME_REGISTRY.get(key) or {}
    return entry.get("adapter")


def get_registered_loop(chat_id: str) -> Any | None:
    """Return the registered event loop for a chat id."""
    key = str(chat_id or "").strip()
    entry = _CHAT_RUNTIME_REGISTRY.get(key) or {}
    return entry.get("loop")
