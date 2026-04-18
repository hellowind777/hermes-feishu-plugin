"""Request-scoped state shared across Feishu plugin patches."""

from __future__ import annotations

import contextvars

_REPLY_TO_MESSAGE_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "hermes_feishu_reply_to_message_id",
    default="",
)
_CHAT_GENERATION: contextvars.ContextVar[int] = contextvars.ContextVar(
    "hermes_feishu_chat_generation",
    default=0,
)


def get_reply_to_message_id() -> str:
    return _REPLY_TO_MESSAGE_ID.get().strip()


def set_reply_to_message_id(message_id: str) -> contextvars.Token[str]:
    return _REPLY_TO_MESSAGE_ID.set(str(message_id or "").strip())


def reset_reply_to_message_id(token: contextvars.Token[str]) -> None:
    _REPLY_TO_MESSAGE_ID.reset(token)


def get_chat_generation() -> int:
    return int(_CHAT_GENERATION.get() or 0)


def set_chat_generation(generation: int) -> contextvars.Token[int]:
    return _CHAT_GENERATION.set(int(generation or 0))


def reset_chat_generation(token: contextvars.Token[int]) -> None:
    _CHAT_GENERATION.reset(token)
