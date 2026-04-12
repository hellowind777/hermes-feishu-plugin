"""Status-message suppression patches."""

from __future__ import annotations

from typing import Any

from ..card.streaming import sync_progress_card
from ..core.i18n import localize_system_text
from ..core.mode import should_stream
from .common import (
    extract_edit_content,
    extract_send_content,
    replace_edit_content,
    replace_send_content,
)
from .runtime_state import remember_tool_steps
from .status_filter import parse_tool_progress_lines, should_suppress_status_message


async def maybe_handle_status_message(
    adapter: Any,
    *,
    chat_id: str,
    content: str,
    metadata: Any = None,
    message_id: str | None = None,
) -> Any | None:
    """Consume Hermes internal progress text and route it into the live card."""
    from gateway.platforms.base import SendResult

    tool_lines = parse_tool_progress_lines(content) if chat_id else []
    if tool_lines:
        remember_tool_steps(adapter, chat_id, tool_lines)
        if should_stream(adapter, chat_id):
            patched_id = await sync_progress_card(adapter, chat_id, metadata=metadata)
            return SendResult(success=True, message_id=patched_id or message_id)
        return SendResult(success=True, message_id=message_id)

    if should_suppress_status_message(content):
        return SendResult(success=True, message_id=message_id)
    return None


def patch_suppress_status_messages() -> bool:
    """Suppress internal progress text so Feishu keeps one live card."""
    from gateway.platforms.feishu import FeishuAdapter

    original_send = FeishuAdapter.send
    if not getattr(original_send, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send(self: Any, *args, **kwargs):
            content = extract_send_content(args, kwargs)
            chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
            handled = await maybe_handle_status_message(
                self,
                chat_id=chat_id,
                content=content,
                metadata=kwargs.get("metadata"),
            )
            if handled is not None:
                return handled
            localized = localize_system_text(content)
            args, kwargs = replace_send_content(args, kwargs, localized)
            return await original_send(self, *args, **kwargs)

        wrapped_send.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.send = wrapped_send

    original_edit = FeishuAdapter.edit_message
    if not getattr(original_edit, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_edit(self: Any, *args, **kwargs):
            content = extract_edit_content(args, kwargs)
            chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
            message_id = str(kwargs.get("message_id") or (args[1] if len(args) >= 2 else "") or "").strip()
            handled = await maybe_handle_status_message(
                self,
                chat_id=chat_id,
                content=content,
                message_id=message_id,
            )
            if handled is not None:
                return handled
            localized = localize_system_text(content)
            args, kwargs = replace_edit_content(args, kwargs, localized)
            return await original_edit(self, *args, **kwargs)

        wrapped_edit.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.edit_message = wrapped_edit

    return True
