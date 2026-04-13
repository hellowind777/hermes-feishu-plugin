"""Shared helpers used by the Feishu streaming-card runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from ..channel.runtime_state import (
    clear_heartbeat_task,
    get_chat_state,
    get_heartbeat_task,
    get_pending_status_text,
    get_reply_target,
    set_heartbeat_task,
)
from ..channel.state import get_reply_to_message_id
from .live_state import visible_tool_steps

logger = logging.getLogger(__name__)

PROGRESS_HEARTBEAT_INTERVAL_SECONDS = 5.0


def is_feishu_adapter(adapter: Any) -> bool:
    """Return True when the current adapter targets Feishu."""
    adapter_name = str(
        getattr(adapter, "name", "")
        or getattr(adapter, "platform", "")
        or ""
    ).strip().lower()
    return adapter_name == "feishu"


def response_ok(response: Any) -> bool:
    """Return True when a Feishu SDK response represents success."""
    return bool(response and getattr(response, "success", lambda: False)())


def resolve_reply_to_message_id(consumer: Any) -> str | None:
    """Resolve the reply target for the active streaming consumer."""
    reply_to = get_reply_to_message_id().strip()
    if reply_to:
        return reply_to
    fallback = get_reply_target(consumer.adapter, consumer.chat_id)
    return fallback or None


def strip_cursor(text: str, cursor: str) -> tuple[str, bool]:
    """Strip the live cursor suffix and report whether the text is final."""
    if cursor and text.endswith(cursor):
        return text[: -len(cursor)], False
    return text, True


async def ensure_progress_heartbeat(
    adapter: Any,
    chat_id: str,
    sync_callback: Callable[[Any, str], Awaitable[Any]],
) -> None:
    """Ensure a low-frequency progress heartbeat exists for the chat."""
    task = get_heartbeat_task(adapter, chat_id)
    if task and not task.done():
        return
    new_task = asyncio.create_task(_progress_heartbeat(adapter, chat_id, sync_callback))
    set_heartbeat_task(adapter, chat_id, new_task)


async def _progress_heartbeat(
    adapter: Any,
    chat_id: str,
    sync_callback: Callable[[Any, str], Awaitable[Any]],
) -> None:
    current_task = asyncio.current_task()
    try:
        while True:
            await asyncio.sleep(PROGRESS_HEARTBEAT_INTERVAL_SECONDS)
            state = get_chat_state(adapter, chat_id)
            if state.phase in {"completed", "aborted", "terminated"} or not state.card_message_id:
                return
            if state.display_text.strip():
                continue
            if not (visible_tool_steps(adapter, chat_id) or get_pending_status_text(adapter, chat_id)):
                continue
            await sync_callback(adapter, chat_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("hermes_feishu_plugin heartbeat skipped: %s", exc)
    finally:
        clear_heartbeat_task(adapter, chat_id, current_task)
