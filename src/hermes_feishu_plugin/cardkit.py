"""Python CardKit helpers aligned with OpenClaw's Feishu transport."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .card_errors import CardKitApiError


def _response_ok(response: Any) -> bool:
    success_fn = getattr(response, "success", None)
    if callable(success_fn) and not success_fn():
        return False
    code = getattr(response, "code", None)
    return code in (None, 0, "0")


def _response_code(response: Any) -> int:
    code = getattr(response, "code", 0)
    if isinstance(code, str) and code.isdigit():
        return int(code)
    return int(code or 0)


def _response_msg(response: Any) -> str:
    return str(getattr(response, "msg", "") or "")


def _assert_cardkit_ok(response: Any, *, api: str, context: str) -> None:
    if _response_ok(response):
        return
    raise CardKitApiError(
        api=api,
        code=_response_code(response),
        msg=_response_msg(response),
        context=context,
    )


async def create_card_entity(adapter: Any, card: dict[str, Any]) -> str:
    """Create a CardKit card entity and return its ``card_id``."""
    from lark_oapi.api.cardkit.v1 import CreateCardRequest, CreateCardRequestBody

    body = (
        CreateCardRequestBody.builder()
        .type("card_json")
        .data(json.dumps(card, ensure_ascii=False))
        .build()
    )
    request = CreateCardRequest.builder().request_body(body).build()
    response = await asyncio.to_thread(adapter._client.cardkit.v1.card.create, request)
    _assert_cardkit_ok(response, api="card.create", context="create streaming card")
    card_id = getattr(getattr(response, "data", None), "card_id", None)
    if not card_id:
        raise RuntimeError("card.create succeeded but no card_id was returned")
    return str(card_id)


async def stream_card_content(
    adapter: Any,
    *,
    card_id: str,
    element_id: str,
    content: str,
    sequence: int,
) -> None:
    """Stream cumulative content into a CardKit element."""
    from lark_oapi.api.cardkit.v1 import ContentCardElementRequest, ContentCardElementRequestBody

    body = (
        ContentCardElementRequestBody.builder()
        .content(content)
        .sequence(sequence)
        .build()
    )
    request = (
        ContentCardElementRequest.builder()
        .card_id(card_id)
        .element_id(element_id)
        .request_body(body)
        .build()
    )
    response = await asyncio.to_thread(adapter._client.cardkit.v1.card_element.content, request)
    _assert_cardkit_ok(response, api="cardElement.content", context=f"seq={sequence}")


async def update_card(
    adapter: Any,
    *,
    card_id: str,
    card: dict[str, Any],
    sequence: int,
) -> None:
    """Replace the full CardKit card body."""
    from lark_oapi.api.cardkit.v1 import UpdateCardRequest, UpdateCardRequestBody

    body = (
        UpdateCardRequestBody.builder()
        .card(json.dumps(card, ensure_ascii=False))
        .sequence(sequence)
        .build()
    )
    request = (
        UpdateCardRequest.builder()
        .card_id(card_id)
        .request_body(body)
        .build()
    )
    response = await asyncio.to_thread(adapter._client.cardkit.v1.card.update, request)
    _assert_cardkit_ok(response, api="card.update", context=f"seq={sequence}")


async def set_card_streaming_mode(
    adapter: Any,
    *,
    card_id: str,
    streaming_mode: bool,
    sequence: int,
) -> None:
    """Toggle CardKit ``streaming_mode``."""
    from lark_oapi.api.cardkit.v1 import SettingsCardRequest, SettingsCardRequestBody

    body = (
        SettingsCardRequestBody.builder()
        .settings(json.dumps({"streaming_mode": streaming_mode}, ensure_ascii=False))
        .sequence(sequence)
        .build()
    )
    request = (
        SettingsCardRequest.builder()
        .card_id(card_id)
        .request_body(body)
        .build()
    )
    response = await asyncio.to_thread(adapter._client.cardkit.v1.card.settings, request)
    _assert_cardkit_ok(response, api="card.settings", context=f"seq={sequence}, streaming={streaming_mode}")


async def send_card_reference(
    adapter: Any,
    *,
    chat_id: str,
    card_id: str,
    reply_to: str | None,
    metadata: Any = None,
) -> Any:
    """Send an ``interactive`` message that references a CardKit ``card_id``."""
    payload = json.dumps(
        {
            "type": "card",
            "data": {"card_id": card_id},
        },
        ensure_ascii=False,
    )
    return await adapter._feishu_send_with_retry(
        chat_id=chat_id,
        msg_type="interactive",
        payload=payload,
        reply_to=reply_to,
        metadata=metadata,
    )


async def send_interactive_card(
    adapter: Any,
    *,
    chat_id: str,
    card: dict[str, Any],
    reply_to: str | None,
    metadata: Any = None,
) -> Any:
    """Send a normal interactive Feishu card without CardKit backing."""
    return await adapter._feishu_send_with_retry(
        chat_id=chat_id,
        msg_type="interactive",
        payload=json.dumps(card, ensure_ascii=False),
        reply_to=reply_to,
        metadata=metadata,
    )


def extract_message_id(response: Any) -> str | None:
    """Extract ``message_id`` from Feishu send responses."""
    data = getattr(response, "data", None)
    for candidate in (
        getattr(data, "message_id", None),
        getattr(response, "message_id", None),
    ):
        if candidate:
            return str(candidate)
    return None


async def patch_interactive_card(
    adapter: Any,
    *,
    message_id: str,
    card: dict[str, Any],
) -> Any:
    """Patch an existing interactive message with new card JSON."""
    from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

    body = (
        PatchMessageRequestBody.builder()
        .content(json.dumps(card, ensure_ascii=False))
        .build()
    )
    request = (
        PatchMessageRequest.builder()
        .message_id(message_id)
        .request_body(body)
        .build()
    )
    return await asyncio.to_thread(adapter._client.im.v1.message.patch, request)
