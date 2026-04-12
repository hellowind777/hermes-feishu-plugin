"""Plugin hook callbacks that mirror OpenClaw-style structured tool trace."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .mode import should_stream
from .runtime_state import get_registered_adapter, get_registered_loop
from .streaming import sync_progress_card
from .tool_display import record_tool_finish, record_tool_start

logger = logging.getLogger(__name__)


def on_pre_tool_call(tool_name: str, args: dict, task_id: str = "", **kwargs: Any) -> None:
    """Record a running tool step for the active Feishu chat."""
    adapter, chat_id, loop = _resolve_runtime()
    if not adapter or not chat_id or not loop or not should_stream(adapter, chat_id):
        return

    try:
        record_tool_start(
            adapter,
            chat_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            task_id=str(task_id or ""),
        )
        asyncio.run_coroutine_threadsafe(sync_progress_card(adapter, chat_id), loop)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin pre_tool_call hook skipped: %s", exc)


def on_post_tool_call(tool_name: str, args: dict, result: str, task_id: str = "", **kwargs: Any) -> None:
    """Mark the most recent matching tool step as success/error."""
    adapter, chat_id, loop = _resolve_runtime()
    if not adapter or not chat_id or not loop or not should_stream(adapter, chat_id):
        return

    try:
        record_tool_finish(
            adapter,
            chat_id,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {},
            result=result,
            task_id=str(task_id or ""),
        )
        asyncio.run_coroutine_threadsafe(sync_progress_card(adapter, chat_id), loop)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin post_tool_call hook skipped: %s", exc)


def _resolve_runtime() -> tuple[Any | None, str, Any | None]:
    platform = str(os.getenv("HERMES_SESSION_PLATFORM", "") or "").strip().lower()
    if platform and platform != "feishu":
        return None, "", None

    chat_id = str(os.getenv("HERMES_SESSION_CHAT_ID", "") or "").strip()
    if not chat_id:
        return None, "", None

    adapter = get_registered_adapter(chat_id)
    loop = get_registered_loop(chat_id)
    return adapter, chat_id, loop
