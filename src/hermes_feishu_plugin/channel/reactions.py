"""Feishu Typing reaction helpers aligned with OpenClaw defaults."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

ACK_EMOJI = "OK"
TYPING_EMOJI = "Typing"


@dataclass(frozen=True)
class FeishuReaction:
    reaction_id: str
    emoji_type: str
    operator_type: str
    operator_id: str


async def add_typing_reaction(adapter: Any, message_id: str) -> Optional[str]:
    if not getattr(adapter, "_client", None) or not message_id:
        return None
    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
        )

        body = (
            CreateMessageReactionRequestBody.builder()
            .reaction_type({"emoji_type": TYPING_EMOJI})
            .build()
        )
        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        response = await asyncio.to_thread(adapter._client.im.v1.message_reaction.create, request)
        if response and getattr(response, "success", lambda: False)():
            return getattr(getattr(response, "data", None), "reaction_id", None)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin add typing reaction failed: %s", exc)
    return None


async def remove_typing_reaction(adapter: Any, message_id: str, reaction_id: str) -> bool:
    if not getattr(adapter, "_client", None) or not message_id or not reaction_id:
        return False
    try:
        from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

        request = (
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        response = await asyncio.to_thread(adapter._client.im.v1.message_reaction.delete, request)
        return bool(response and getattr(response, "success", lambda: False)())
    except Exception as exc:
        logger.debug("hermes_feishu_plugin remove typing reaction failed: %s", exc)
        return False


async def list_reactions(
    adapter: Any,
    message_id: str,
    *,
    emoji_type: Optional[str] = None,
) -> list[FeishuReaction]:
    if not getattr(adapter, "_client", None) or not message_id:
        return []

    try:
        from lark_oapi.api.im.v1 import ListMessageReactionRequest

        reactions: list[FeishuReaction] = []
        page_token: Optional[str] = None
        while True:
            builder = (
                ListMessageReactionRequest.builder()
                .message_id(message_id)
                .page_size(50)
            )
            if emoji_type:
                builder = builder.reaction_type(emoji_type)
            if page_token:
                builder = builder.page_token(page_token)

            request = builder.build()
            response = await asyncio.to_thread(adapter._client.im.v1.message_reaction.list, request)
            if not response or not getattr(response, "success", lambda: False)():
                logger.warning(
                    "hermes_feishu_plugin failed to list ACK reactions: message_id=%s emoji=%s code=%s msg=%s",
                    message_id,
                    emoji_type,
                    getattr(response, "code", None),
                    getattr(response, "msg", None),
                )
                return reactions

            data = getattr(response, "data", None)
            for item in list(getattr(data, "items", None) or []):
                reaction_type = getattr(item, "reaction_type", None)
                operator = getattr(item, "operator", None)
                reactions.append(
                    FeishuReaction(
                        reaction_id=str(getattr(item, "reaction_id", "") or ""),
                        emoji_type=str(getattr(reaction_type, "emoji_type", "") or ""),
                        operator_type=str(getattr(operator, "operator_type", "") or ""),
                        operator_id=str(getattr(operator, "operator_id", "") or ""),
                    )
                )

            has_more = bool(getattr(data, "has_more", False))
            page_token = str(getattr(data, "page_token", "") or "").strip() or None
            if not has_more or not page_token:
                return reactions
    except Exception as exc:
        logger.debug("hermes_feishu_plugin list reactions failed: %s", exc)
        return []


async def remove_reaction(adapter: Any, message_id: str, reaction_id: str) -> bool:
    if not getattr(adapter, "_client", None) or not message_id or not reaction_id:
        return False

    try:
        from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

        request = (
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        response = await asyncio.to_thread(adapter._client.im.v1.message_reaction.delete, request)
        return bool(response and getattr(response, "success", lambda: False)())
    except Exception as exc:
        logger.debug("hermes_feishu_plugin remove reaction failed: %s", exc)
        return False


async def clear_ack_reactions(adapter: Any, message_id: str) -> int:
    removed = 0
    reactions = await list_reactions(adapter, message_id, emoji_type=ACK_EMOJI)
    for reaction in reactions:
        if await remove_reaction(adapter, message_id, reaction.reaction_id):
            removed += 1
        else:
            logger.warning(
                "hermes_feishu_plugin failed to remove ACK reaction: message_id=%s reaction_id=%s operator=%s/%s",
                message_id,
                reaction.reaction_id,
                reaction.operator_type,
                reaction.operator_id,
            )
    if reactions or removed:
        logger.info(
            "hermes_feishu_plugin ACK cleanup checked: message_id=%s candidates=%d removed=%d",
            message_id,
            len(reactions),
            removed,
        )
    return removed
