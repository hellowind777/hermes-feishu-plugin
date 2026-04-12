"""Feishu streaming-card transport aligned with the OpenClaw interaction style."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .card_builder import build_streaming_card
from .mode import should_stream
from .status_filter import should_suppress_status_message
from .runtime_state import (
    get_card_message_id,
    get_display_text,
    get_generation,
    get_heartbeat_task,
    get_last_card_update_at,
    get_reply_target,
    get_tool_steps,
    clear_heartbeat_task,
    remember_card_message,
    remember_display_text,
    set_heartbeat_task,
)
from .state import get_reply_to_message_id

logger = logging.getLogger(__name__)
CARD_EDIT_INTERVAL_SECONDS = 1.2
CARD_UPDATE_RETRY_DELAYS = (0.0, 0.35, 0.8)
HEARTBEAT_INTERVAL_SECONDS = 4.0


def _is_feishu_adapter(adapter: Any) -> bool:
    adapter_name = str(
        getattr(adapter, "name", "")
        or getattr(adapter, "platform", "")
        or ""
    ).strip().lower()
    return adapter_name == "feishu"


def _response_ok(response: Any) -> bool:
    return bool(response and getattr(response, "success", lambda: False)())


def _response_error(response: Any) -> str:
    if response is None:
        return "empty response"
    code = getattr(response, "code", None)
    msg = getattr(response, "msg", None)
    error = getattr(response, "error", None)
    return f"code={code} msg={msg} error={error}"


def _resolve_reply_to_message_id(consumer: Any) -> str | None:
    reply_to = get_reply_to_message_id().strip()
    if reply_to:
        return reply_to

    fallback = get_reply_target(consumer.adapter, consumer.chat_id)
    return fallback or None


def _build_patch_message_request(message_id: str, content: str) -> Any:
    try:
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

        body = PatchMessageRequestBody.builder().content(content).build()
        return (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
    except Exception:
        from types import SimpleNamespace

        return SimpleNamespace(message_id=message_id, request_body=SimpleNamespace(content=content))


async def _send_card_message(
    consumer: Any,
    text: str,
    *,
    is_final: bool,
) -> tuple[bool, str | None]:
    payload = build_streaming_card(consumer.adapter, consumer.chat_id, text, is_final=is_final)
    response = await consumer.adapter._feishu_send_with_retry(
        chat_id=consumer.chat_id,
        msg_type="interactive",
        payload=payload,
        reply_to=_resolve_reply_to_message_id(consumer),
        metadata=consumer.metadata,
    )
    if consumer.adapter._response_succeeded(response):
        setattr(consumer, "_feishu_card_last_update_time", time.monotonic())
        message_id = consumer.adapter._extract_response_field(response, "message_id")
        remember_card_message(consumer.adapter, consumer.chat_id, message_id)
        remember_display_text(consumer.adapter, consumer.chat_id, text)
        if not is_final:
            _ensure_heartbeat_task(consumer.adapter, consumer.chat_id)
        return True, message_id
    return False, None


async def _update_card_message(
    consumer: Any,
    text: str,
    *,
    is_final: bool,
) -> bool:
    payload = build_streaming_card(consumer.adapter, consumer.chat_id, text, is_final=is_final)
    last_error = ""
    for delay in CARD_UPDATE_RETRY_DELAYS:
        if delay > 0:
            await asyncio.sleep(delay)
        request = _build_patch_message_request(consumer._message_id, payload)
        response = await asyncio.to_thread(consumer.adapter._client.im.v1.message.patch, request)
        if _response_ok(response):
            setattr(consumer, "_feishu_card_last_update_time", time.monotonic())
            remember_card_message(consumer.adapter, consumer.chat_id, consumer._message_id)
            remember_display_text(consumer.adapter, consumer.chat_id, text)
            if is_final:
                _cancel_heartbeat_task(consumer.adapter, consumer.chat_id)
            else:
                _ensure_heartbeat_task(consumer.adapter, consumer.chat_id)
            return True
        last_error = _response_error(response)
    logger.warning(
        "hermes_feishu_plugin Feishu card patch failed: message_id=%s final=%s %s",
        consumer._message_id,
        is_final,
        last_error,
    )
    return False


async def _fallback_text_update(consumer: Any, text: str) -> bool:
    result = await consumer.adapter.edit_message(
        chat_id=consumer.chat_id,
        message_id=consumer._message_id,
        content=text,
    )
    if result.success:
        consumer._already_sent = True
        consumer._last_sent_text = text
        remember_display_text(consumer.adapter, consumer.chat_id, text)
        _cancel_heartbeat_task(consumer.adapter, consumer.chat_id)
        return True
    return False


async def _patch_card_message(
    adapter: Any,
    chat_id: str,
    message_id: str,
    text: str,
    *,
    is_final: bool,
) -> bool:
    payload = build_streaming_card(adapter, chat_id, text, is_final=is_final)
    last_error = ""
    for delay in CARD_UPDATE_RETRY_DELAYS:
        if delay > 0:
            await asyncio.sleep(delay)
        request = _build_patch_message_request(message_id, payload)
        response = await asyncio.to_thread(adapter._client.im.v1.message.patch, request)
        if _response_ok(response):
            remember_card_message(adapter, chat_id, message_id)
            remember_display_text(adapter, chat_id, text)
            if is_final:
                _cancel_heartbeat_task(adapter, chat_id)
            else:
                _ensure_heartbeat_task(adapter, chat_id)
            return True
        last_error = _response_error(response)
    logger.warning(
        "hermes_feishu_plugin Feishu card patch failed: message_id=%s final=%s %s",
        message_id,
        is_final,
        last_error,
    )
    return False


async def _heartbeat_loop(adapter: Any, chat_id: str, generation: int) -> None:
    current_task = asyncio.current_task()
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if not should_stream(adapter, chat_id):
                return
            if get_generation(adapter, chat_id) != generation:
                return
            message_id = get_card_message_id(adapter, chat_id)
            if not message_id:
                continue
            last_update_at = get_last_card_update_at(adapter, chat_id)
            if last_update_at and (time.monotonic() - last_update_at) < HEARTBEAT_INTERVAL_SECONDS:
                continue
            text = get_display_text(adapter, chat_id)
            if not str(text or "").strip() and not get_tool_steps(adapter, chat_id):
                continue
            await _patch_card_message(adapter, chat_id, message_id, text, is_final=False)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("hermes_feishu_plugin heartbeat error for %s: %s", chat_id, exc)
    finally:
        clear_heartbeat_task(adapter, chat_id, current_task)


def _ensure_heartbeat_task(adapter: Any, chat_id: str) -> None:
    current = get_heartbeat_task(adapter, chat_id)
    if current and not bool(getattr(current, "done", lambda: True)()):
        return
    generation = get_generation(adapter, chat_id)
    task = asyncio.create_task(_heartbeat_loop(adapter, chat_id, generation))
    set_heartbeat_task(adapter, chat_id, task)


def _cancel_heartbeat_task(adapter: Any, chat_id: str) -> None:
    task = get_heartbeat_task(adapter, chat_id)
    if task and not bool(getattr(task, "done", lambda: True)()):
        task.cancel()
    clear_heartbeat_task(adapter, chat_id)


async def sync_progress_card(adapter: Any, chat_id: str, metadata: Any = None) -> str | None:
    """Create or update the single Feishu reply card for tool-progress updates."""
    if not should_stream(adapter, chat_id):
        return None

    text = get_display_text(adapter, chat_id)
    message_id = get_card_message_id(adapter, chat_id)
    payload = build_streaming_card(adapter, chat_id, text, is_final=False)

    if not message_id:
        reply_to = get_reply_target(adapter, chat_id)
        if not reply_to:
            return None
        response = await adapter._feishu_send_with_retry(
            chat_id=chat_id,
            msg_type="interactive",
            payload=payload,
            reply_to=reply_to,
            metadata=metadata,
        )
        if not adapter._response_succeeded(response):
            return None
        message_id = adapter._extract_response_field(response, "message_id")
        remember_card_message(adapter, chat_id, message_id)
        _ensure_heartbeat_task(adapter, chat_id)
        return message_id

    if not await _patch_card_message(adapter, chat_id, message_id, text, is_final=False):
        return None
    return message_id


def patch_streaming_cards() -> bool:
    import gateway.stream_consumer as stream_consumer

    original_send_or_edit = stream_consumer.GatewayStreamConsumer._send_or_edit
    original_on_delta = stream_consumer.GatewayStreamConsumer.on_delta

    if not getattr(original_on_delta, "__hermes_feishu_plugin_wrapped__", False):
        def wrapped_on_delta(self: Any, text: str | None) -> None:
            if text is None and _is_feishu_adapter(self.adapter):
                return
            return original_on_delta(self, text)

        wrapped_on_delta.__hermes_feishu_plugin_wrapped__ = True
        stream_consumer.GatewayStreamConsumer.on_delta = wrapped_on_delta

    if getattr(original_send_or_edit, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_send_or_edit(self: Any, text: str) -> None:
        cleaned = self._clean_for_display(text)
        if not cleaned.strip():
            return
        if should_suppress_status_message(cleaned):
            logger.info(
                "hermes_feishu_plugin suppressed Feishu streaming status: %s",
                cleaned.splitlines()[0][:160],
            )
            self._already_sent = True
            return
        if not _is_feishu_adapter(self.adapter):
            return await original_send_or_edit(self, text)
        if not should_stream(self.adapter, self.chat_id):
            return await original_send_or_edit(self, text)
        if cleaned == self._last_sent_text:
            return

        is_final = not (self.cfg.cursor and cleaned.endswith(self.cfg.cursor))
        try:
            remembered_message_id = get_card_message_id(self.adapter, self.chat_id)
            if self._message_id is None and remembered_message_id:
                self._message_id = remembered_message_id
            if self._message_id is None:
                ok, message_id = await _send_card_message(self, cleaned, is_final=is_final)
                if ok and message_id:
                    self._message_id = message_id
                    self._already_sent = True
                    self._last_sent_text = cleaned
                    return
                return await original_send_or_edit(self, text)

            last_update_time = float(getattr(self, "_feishu_card_last_update_time", 0.0) or 0.0)
            now = time.monotonic()
            if not is_final and last_update_time and (now - last_update_time) < CARD_EDIT_INTERVAL_SECONDS:
                self._already_sent = True
                return

            if await _update_card_message(self, cleaned, is_final=is_final):
                self._already_sent = True
                self._last_sent_text = cleaned
                return

            if is_final and await _fallback_text_update(self, cleaned):
                return
            self._already_sent = True
            logger.warning("hermes_feishu_plugin could not update Feishu card; suppressing text fallback to avoid duplicate messages")
        except Exception as exc:
            logger.warning("hermes_feishu_plugin streaming card error: %s", exc)
            if self._message_id is None:
                await original_send_or_edit(self, text)
            else:
                self._already_sent = True

    wrapped_send_or_edit.__hermes_feishu_plugin_wrapped__ = True
    stream_consumer.GatewayStreamConsumer._send_or_edit = wrapped_send_or_edit
    return True
