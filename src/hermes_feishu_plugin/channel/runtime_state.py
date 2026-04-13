"""Per-chat runtime state for the Hermes Feishu plugin."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any

from ..card.models import ToolDisplayStep

_CHAT_STATE_ATTR = "_hermes_feishu_chat_state"
_CHAT_RUNTIME_REGISTRY: dict[str, dict[str, Any]] = {}


@dataclass
class ChatRuntimeState:
    """Mutable chat-scoped state used by Feishu runtime patches."""

    generation: int = 0
    reply_to_message_id: str = ""
    chat_type: str = "dm"
    started_at: float = 0.0
    phase: str = "idle"
    card_id: str = ""
    original_card_id: str = ""
    card_sequence: int = 0
    card_message_id: str = ""
    cardkit_streaming_enabled: bool = True
    last_card_update_at: float = 0.0
    last_tool_status_update_at: float = 0.0
    last_visible_activity_at: float = 0.0
    display_text: str = ""
    pending_status_text: str = ""
    heartbeat_status_text: str = ""
    last_flushed_text: str = ""
    tool_started_at: float = 0.0
    tool_elapsed_ms: int = 0
    tool_steps: list[ToolDisplayStep] = field(default_factory=list)
    fallback_tool_lines: list[str] = field(default_factory=list)
    tool_call_indices: dict[str, list[int]] = field(default_factory=dict)
    fallback_switch_count: int = 0
    card_create_lock: Any = None
    card_update_lock: Any = None
    flush_controller: Any = None
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


def reset_chat_state(
    adapter: Any,
    chat_id: str,
    *,
    reply_to_message_id: str = "",
    chat_type: str = "dm",
) -> ChatRuntimeState:
    """Reset chat state for a new inbound request."""
    key = str(chat_id or "").strip()
    previous = _get_state_map(adapter).get(key)
    previous_generation = previous.generation if isinstance(previous, ChatRuntimeState) else 0

    for task in (
        getattr(previous, "heartbeat_task", None),
        getattr(getattr(previous, "flush_controller", None), "_pending_timer", None),
    ):
        if task and hasattr(task, "cancel"):
            try:
                task.cancel()
            except Exception:
                pass

    now = time.monotonic()
    state = ChatRuntimeState(
        generation=previous_generation + 1,
        reply_to_message_id=str(reply_to_message_id or "").strip(),
        chat_type=_normalize_chat_type(chat_type),
        started_at=now,
        last_visible_activity_at=now,
        phase="idle",
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
    get_chat_state(adapter, chat_id).reply_to_message_id = str(message_id or "").strip()


def get_reply_target(adapter: Any, chat_id: str) -> str:
    """Return the latest reply target for a chat."""
    return get_chat_state(adapter, chat_id).reply_to_message_id.strip()


def remember_card_entity(adapter: Any, chat_id: str, card_id: str) -> None:
    """Persist the CardKit card identity."""
    state = get_chat_state(adapter, chat_id)
    normalized = str(card_id or "").strip()
    state.card_id = normalized
    state.original_card_id = normalized
    state.card_sequence = max(1, state.card_sequence)
    state.cardkit_streaming_enabled = bool(normalized)


def disable_cardkit_streaming(adapter: Any, chat_id: str) -> None:
    """Disable CardKit intermediate streaming while keeping final update target."""
    state = get_chat_state(adapter, chat_id)
    state.card_id = ""
    state.cardkit_streaming_enabled = False


def get_card_id(adapter: Any, chat_id: str) -> str:
    """Return the active CardKit card id used for streaming."""
    return get_chat_state(adapter, chat_id).card_id.strip()


def get_original_card_id(adapter: Any, chat_id: str) -> str:
    """Return the original CardKit card id for final updates."""
    return get_chat_state(adapter, chat_id).original_card_id.strip()


def advance_card_sequence(adapter: Any, chat_id: str) -> int:
    """Bump and return the per-card sequence."""
    state = get_chat_state(adapter, chat_id)
    state.card_sequence += 1
    return state.card_sequence


def remember_card_message(adapter: Any, chat_id: str, message_id: str) -> None:
    """Persist the active streaming-card message id."""
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
    """Persist the latest visible streamed text."""
    state = get_chat_state(adapter, chat_id)
    next_text = str(text or "")
    if next_text != state.display_text and next_text.strip():
        note_visible_activity(adapter, chat_id)
        state.pending_status_text = ""
    state.display_text = next_text


def get_display_text(adapter: Any, chat_id: str) -> str:
    """Return the latest visible streamed text."""
    return get_chat_state(adapter, chat_id).display_text


def remember_pending_status_text(adapter: Any, chat_id: str, text: str) -> None:
    """Persist the latest pre-answer status text shown in the live card."""
    state = get_chat_state(adapter, chat_id)
    next_text = str(text or "").strip()
    if next_text and next_text != state.pending_status_text:
        note_visible_activity(adapter, chat_id)
    state.pending_status_text = next_text


def get_pending_status_text(adapter: Any, chat_id: str) -> str:
    """Return the latest pre-answer status text."""
    return get_chat_state(adapter, chat_id).pending_status_text.strip()


def get_heartbeat_status_text(adapter: Any, chat_id: str) -> str:
    """Return the lightweight in-card heartbeat text."""
    return get_chat_state(adapter, chat_id).heartbeat_status_text.strip()


def set_heartbeat_status_text(adapter: Any, chat_id: str, text: str) -> None:
    """Persist the lightweight in-card heartbeat text."""
    get_chat_state(adapter, chat_id).heartbeat_status_text = str(text or "").strip()


def remember_last_flushed_text(adapter: Any, chat_id: str, text: str) -> None:
    """Persist the last text successfully flushed to Feishu."""
    state = get_chat_state(adapter, chat_id)
    state.last_flushed_text = str(text or "")
    state.last_card_update_at = time.monotonic()


def get_last_flushed_text(adapter: Any, chat_id: str) -> str:
    """Return the last text successfully flushed to Feishu."""
    return get_chat_state(adapter, chat_id).last_flushed_text


def remember_tool_steps(adapter: Any, chat_id: str, tool_steps: list[Any]) -> None:
    """Persist fallback tool-progress lines or structured tool steps."""
    state = get_chat_state(adapter, chat_id)
    structured = [step for step in tool_steps if isinstance(step, ToolDisplayStep)]
    if structured:
        if structured != state.tool_steps:
            note_visible_activity(adapter, chat_id)
        state.tool_steps = structured
        state.fallback_tool_lines.clear()
        return
    next_lines = [str(step).strip() for step in tool_steps if str(step).strip()]
    if next_lines != state.fallback_tool_lines and next_lines:
        note_visible_activity(adapter, chat_id)
    state.fallback_tool_lines = next_lines


def get_tool_steps(adapter: Any, chat_id: str) -> list[ToolDisplayStep]:
    """Return structured tool-use steps."""
    return list(get_chat_state(adapter, chat_id).tool_steps)


def get_fallback_tool_lines(adapter: Any, chat_id: str) -> list[str]:
    """Return fallback plain progress lines."""
    return list(get_chat_state(adapter, chat_id).fallback_tool_lines)


def get_tool_elapsed_ms(adapter: Any, chat_id: str) -> int | None:
    """Return elapsed tool-use duration in milliseconds."""
    state = get_chat_state(adapter, chat_id)
    if state.tool_started_at <= 0:
        return None
    if state.tool_elapsed_ms:
        return state.tool_elapsed_ms
    return int(max(0.0, time.monotonic() - state.tool_started_at) * 1000)


def get_chat_type(adapter: Any, chat_id: str) -> str:
    """Return normalized chat type for a chat."""
    return get_chat_state(adapter, chat_id).chat_type


def get_elapsed_seconds(adapter: Any, chat_id: str) -> float | None:
    """Return elapsed processing time for a chat."""
    started_at = get_chat_state(adapter, chat_id).started_at
    if started_at <= 0:
        return None
    return max(0.0, time.monotonic() - started_at)


def note_visible_activity(adapter: Any, chat_id: str) -> None:
    """Record visible progress and clear any stale heartbeat notice."""
    state = get_chat_state(adapter, chat_id)
    state.last_visible_activity_at = time.monotonic()
    state.heartbeat_status_text = ""


def get_last_visible_activity_at(adapter: Any, chat_id: str) -> float:
    """Return the last time the live card showed real progress."""
    state = get_chat_state(adapter, chat_id)
    return float(state.last_visible_activity_at or state.started_at or 0.0)


def get_heartbeat_task(adapter: Any, chat_id: str) -> Any:
    """Return the active heartbeat task, if any."""
    return get_chat_state(adapter, chat_id).heartbeat_task


def set_heartbeat_task(adapter: Any, chat_id: str, task: Any) -> None:
    """Persist the active heartbeat task."""
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
    return (_CHAT_RUNTIME_REGISTRY.get(str(chat_id or "").strip()) or {}).get("adapter")


def get_registered_loop(chat_id: str) -> Any | None:
    """Return the registered event loop for a chat id."""
    return (_CHAT_RUNTIME_REGISTRY.get(str(chat_id or "").strip()) or {}).get("loop")
