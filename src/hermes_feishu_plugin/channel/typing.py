"""Typing-reaction and ACK suppression patches."""

from __future__ import annotations

import asyncio
from typing import Any

from ..card.streaming import sync_progress_card
from .common import clear_ack_reactions_later, ensure_runtime_state
from .reactions import add_typing_reaction, clear_ack_reactions, remove_typing_reaction
from .runtime_state import remember_inbound_message, remember_reply_target
from .state import get_reply_to_message_id, reset_reply_to_message_id, set_reply_to_message_id


def patch_disable_ack_reaction() -> bool:
    """Disable Hermes' old persistent OK acknowledgement reaction."""
    from gateway.platforms.feishu import FeishuAdapter

    original_add_ack = FeishuAdapter._add_ack_reaction
    if getattr(original_add_ack, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_add_ack(self: Any, message_id: str):
        if message_id:
            await clear_ack_reactions(self, message_id)
        return None

    wrapped_add_ack.__hermes_feishu_plugin_wrapped__ = True
    FeishuAdapter._add_ack_reaction = wrapped_add_ack
    return True


def patch_typing_reaction() -> bool:
    """Use official-style transient Typing reaction while processing."""
    from gateway.platforms.feishu import FeishuAdapter

    original_guarded = FeishuAdapter._handle_message_with_guards
    original_send_typing = FeishuAdapter.send_typing
    original_stop_typing = FeishuAdapter.stop_typing

    if not getattr(original_send_typing, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send_typing(self: Any, chat_id: str, metadata=None) -> None:
            reply_targets, typing_reactions = ensure_runtime_state(self)
            message_id = get_reply_to_message_id() or str(reply_targets.get(chat_id, "") or "").strip()
            if not message_id:
                return await original_send_typing(self, chat_id, metadata=metadata)

            active = typing_reactions.get(chat_id)
            if active and active[0] == message_id and active[1]:
                return None
            if active and active[0] and active[1]:
                await remove_typing_reaction(self, active[0], active[1])
                typing_reactions.pop(chat_id, None)

            await clear_ack_reactions(self, message_id)
            await sync_progress_card(self, chat_id, metadata=metadata)
            reaction_id = await add_typing_reaction(self, message_id)
            if reaction_id:
                typing_reactions[chat_id] = (message_id, reaction_id)
                reply_targets[chat_id] = message_id
                return None
            return await original_send_typing(self, chat_id, metadata=metadata)

        wrapped_send_typing.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.send_typing = wrapped_send_typing

    if not getattr(original_stop_typing, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_stop_typing(self: Any, chat_id: str) -> None:
            reply_targets, typing_reactions = ensure_runtime_state(self)
            active = typing_reactions.pop(chat_id, None)
            if active and active[0] and active[1]:
                await remove_typing_reaction(self, active[0], active[1])
            current_target = str(reply_targets.get(chat_id, "") or "").strip()
            if not current_target or not active or current_target == active[0]:
                reply_targets.pop(chat_id, None)
            return await original_stop_typing(self, chat_id)

        wrapped_stop_typing.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.stop_typing = wrapped_stop_typing

    if getattr(original_guarded, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_guarded(self: Any, event: Any) -> None:
        source = getattr(event, "source", None)
        chat_id = getattr(source, "chat_id", "") or ""
        chat_lock = self._get_chat_lock(chat_id)
        message_id = getattr(event, "message_id", "") or ""
        chat_type = getattr(source, "chat_type", "dm") if source else "dm"
        reply_targets, _typing_reactions = ensure_runtime_state(self)
        reply_token = set_reply_to_message_id(message_id)

        async with chat_lock:
            try:
                if message_id:
                    reply_targets[chat_id] = message_id
                    remember_reply_target(self, chat_id, message_id)
                    remember_inbound_message(self, chat_id, message_id, chat_type)
                    await clear_ack_reactions(self, message_id)
                    asyncio.create_task(clear_ack_reactions_later(self, message_id, 1.0))
                await self.handle_message(event)
            finally:
                reset_reply_to_message_id(reply_token)
                if message_id:
                    await clear_ack_reactions(self, message_id)
                    asyncio.create_task(clear_ack_reactions_later(self, message_id, 3.0))

    wrapped_guarded.__hermes_feishu_plugin_wrapped__ = True
    FeishuAdapter._handle_message_with_guards = wrapped_guarded
    return True
