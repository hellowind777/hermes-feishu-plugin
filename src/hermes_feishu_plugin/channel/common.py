"""Shared channel patch helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from .reactions import clear_ack_reactions

REPLY_TARGETS_ATTR = "_hermes_feishu_reply_targets"
TYPING_REACTIONS_ATTR = "_hermes_feishu_typing_reactions"


def extract_send_content(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Extract send-message content from positional or keyword args."""
    if "content" in kwargs:
        return str(kwargs.get("content") or "")
    if len(args) >= 2:
        return str(args[1] or "")
    return ""


def extract_edit_content(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Extract edit-message content from positional or keyword args."""
    if "content" in kwargs:
        return str(kwargs.get("content") or "")
    if len(args) >= 3:
        return str(args[2] or "")
    return ""


def replace_send_content(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    content: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Replace send-message content in positional or keyword args."""
    new_kwargs = dict(kwargs)
    if "content" in new_kwargs:
        new_kwargs["content"] = content
        return args, new_kwargs
    if len(args) >= 2:
        new_args = list(args)
        new_args[1] = content
        return tuple(new_args), new_kwargs
    new_kwargs["content"] = content
    return args, new_kwargs


def replace_edit_content(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    content: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Replace edit-message content in positional or keyword args."""
    new_kwargs = dict(kwargs)
    if "content" in new_kwargs:
        new_kwargs["content"] = content
        return args, new_kwargs
    if len(args) >= 3:
        new_args = list(args)
        new_args[2] = content
        return tuple(new_args), new_kwargs
    new_kwargs["content"] = content
    return args, new_kwargs


async def clear_ack_reactions_later(adapter: Any, message_id: str, delay: float) -> None:
    """Clear ACK reactions after a short delay."""
    await asyncio.sleep(delay)
    await clear_ack_reactions(adapter, message_id)


def ensure_runtime_state(adapter: Any) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Ensure reply-target and typing-reaction maps exist on the adapter."""
    reply_targets = getattr(adapter, REPLY_TARGETS_ATTR, None)
    if not isinstance(reply_targets, dict):
        reply_targets = {}
        setattr(adapter, REPLY_TARGETS_ATTR, reply_targets)

    typing_reactions = getattr(adapter, TYPING_REACTIONS_ATTR, None)
    if not isinstance(typing_reactions, dict):
        typing_reactions = {}
        setattr(adapter, TYPING_REACTIONS_ATTR, typing_reactions)

    return reply_targets, typing_reactions
