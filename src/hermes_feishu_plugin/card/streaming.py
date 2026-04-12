"""Feishu CardKit-first streaming transport aligned with OpenClaw."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..channel.runtime_state import (
    advance_card_sequence,
    disable_cardkit_streaming,
    get_card_id,
    get_card_message_id,
    get_chat_state,
    get_display_text,
    get_elapsed_seconds,
    get_fallback_tool_lines,
    get_last_flushed_text,
    get_original_card_id,
    get_reply_target,
    get_tool_elapsed_ms,
    get_tool_steps,
    remember_card_entity,
    remember_card_message,
    remember_display_text,
    remember_last_flushed_text,
    remember_tool_steps,
)
from ..channel.state import get_reply_to_message_id
from ..channel.status_filter import parse_tool_progress_lines, should_suppress_status_message
from ..core.mode import should_stream
from .builder import (
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_patch_card,
    build_streaming_pre_answer_card,
    to_cardkit2,
)
from .cardkit import (
    create_card_entity,
    extract_message_id,
    patch_interactive_card,
    send_card_reference,
    send_interactive_card,
    set_card_streaming_mode,
    stream_card_content,
    update_card,
)
from .errors import is_card_rate_limit_error, is_card_table_limit_error
from .flush_controller import FlushController
from .tool_display import fallback_steps_from_lines

logger = logging.getLogger(__name__)

CARDKIT_UPDATE_INTERVAL_SECONDS = 0.1
PATCH_UPDATE_INTERVAL_SECONDS = 1.5
TOOL_STATUS_UPDATE_INTERVAL_SECONDS = 1.5


def _is_feishu_adapter(adapter: Any) -> bool:
    adapter_name = str(
        getattr(adapter, "name", "")
        or getattr(adapter, "platform", "")
        or ""
    ).strip().lower()
    return adapter_name == "feishu"


def _response_ok(response: Any) -> bool:
    return bool(response and getattr(response, "success", lambda: False)())


def _resolve_reply_to_message_id(consumer: Any) -> str | None:
    reply_to = get_reply_to_message_id().strip()
    if reply_to:
        return reply_to
    fallback = get_reply_target(consumer.adapter, consumer.chat_id)
    return fallback or None


def _visible_tool_steps(adapter: Any, chat_id: str) -> list[Any]:
    steps = get_tool_steps(adapter, chat_id)
    if steps:
        return steps
    return fallback_steps_from_lines(get_fallback_tool_lines(adapter, chat_id))


def _elapsed_ms(adapter: Any, chat_id: str) -> int | None:
    seconds = get_elapsed_seconds(adapter, chat_id)
    if seconds is None:
        return None
    return int(seconds * 1000)


async def _ensure_card_created(
    adapter: Any,
    chat_id: str,
    *,
    reply_to: str | None,
    metadata: Any = None,
) -> str | None:
    """Create the single reply card via CardKit, falling back to IM card."""
    state = get_chat_state(adapter, chat_id)
    if state.card_message_id:
        return state.card_message_id
    if not reply_to:
        return None

    steps = _visible_tool_steps(adapter, chat_id)
    tool_elapsed_ms = get_tool_elapsed_ms(adapter, chat_id)
    initial_card = build_streaming_pre_answer_card(
        tool_steps=steps,
        tool_elapsed_ms=tool_elapsed_ms,
    )

    try:
        card_id = await create_card_entity(adapter, initial_card)
        remember_card_entity(adapter, chat_id, card_id)
        response = await send_card_reference(
            adapter,
            chat_id=chat_id,
            card_id=card_id,
            reply_to=reply_to,
            metadata=metadata,
        )
        if not _response_ok(response):
            raise RuntimeError(f"send CardKit reference failed: code={getattr(response, 'code', None)} msg={getattr(response, 'msg', None)}")
        message_id = extract_message_id(response)
        if not message_id:
            raise RuntimeError("send CardKit reference succeeded but no message_id was returned")
        remember_card_message(adapter, chat_id, message_id)
        state.phase = "streaming"
        state.flush_controller = FlushController(lambda: _perform_answer_flush(adapter, chat_id))
        state.flush_controller.set_ready(True)
        return message_id
    except Exception as exc:
        logger.warning("hermes_feishu_plugin CardKit flow failed; falling back to IM card: %s", exc)
        disable_cardkit_streaming(adapter, chat_id)
        if not state.card_message_id:
            state.original_card_id = ""
            state.card_sequence = 0

    fallback_card = build_streaming_patch_card(tool_steps=steps)
    response = await send_interactive_card(
        adapter,
        chat_id=chat_id,
        card=fallback_card,
        reply_to=reply_to,
        metadata=metadata,
    )
    if not _response_ok(response):
        logger.warning(
            "hermes_feishu_plugin fallback IM card send failed: code=%s msg=%s",
            getattr(response, "code", None),
            getattr(response, "msg", None),
        )
        return None
    message_id = extract_message_id(response)
    if message_id:
        remember_card_message(adapter, chat_id, message_id)
        state.phase = "streaming"
        state.flush_controller = FlushController(lambda: _perform_answer_flush(adapter, chat_id))
        state.flush_controller.set_ready(True)
    return message_id


async def _perform_answer_flush(adapter: Any, chat_id: str) -> None:
    """Flush accumulated answer text via CardKit or IM patch fallback."""
    state = get_chat_state(adapter, chat_id)
    message_id = state.card_message_id
    if not message_id or state.phase in {"completed", "aborted", "terminated"}:
        return

    text = state.display_text
    if text == state.last_flushed_text:
        return

    active_card_id = get_card_id(adapter, chat_id)
    if active_card_id:
        sequence = advance_card_sequence(adapter, chat_id)
        try:
            await stream_card_content(
                adapter,
                card_id=active_card_id,
                element_id=STREAMING_ELEMENT_ID,
                content=text,
                sequence=sequence,
            )
            remember_last_flushed_text(adapter, chat_id, text)
            return
        except Exception as exc:
            if is_card_rate_limit_error(exc):
                logger.info("hermes_feishu_plugin CardKit rate limited; skipping frame")
                return
            if is_card_table_limit_error(exc):
                logger.warning("hermes_feishu_plugin CardKit table limit hit; disabling intermediate CardKit streaming")
                disable_cardkit_streaming(adapter, chat_id)
                return
            logger.warning("hermes_feishu_plugin CardKit stream failed; disabling CardKit streaming: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)

    if get_original_card_id(adapter, chat_id):
        return

    card = build_streaming_patch_card(text=text, tool_steps=_visible_tool_steps(adapter, chat_id))
    response = await patch_interactive_card(adapter, message_id=message_id, card=card)
    if _response_ok(response):
        remember_last_flushed_text(adapter, chat_id, text)


async def _flush_answer(adapter: Any, chat_id: str) -> None:
    state = get_chat_state(adapter, chat_id)
    if not state.flush_controller:
        state.flush_controller = FlushController(lambda: _perform_answer_flush(adapter, chat_id))
        state.flush_controller.set_ready(bool(state.card_message_id))
    throttle = CARDKIT_UPDATE_INTERVAL_SECONDS if get_card_id(adapter, chat_id) else PATCH_UPDATE_INTERVAL_SECONDS
    await state.flush_controller.throttled_update(throttle)


async def sync_progress_card(adapter: Any, chat_id: str, metadata: Any = None) -> str | None:
    """Create or update the single Feishu reply card for tool-progress updates."""
    if not should_stream(adapter, chat_id):
        return None

    state = get_chat_state(adapter, chat_id)
    reply_to = state.reply_to_message_id or get_reply_to_message_id().strip()
    message_id = await _ensure_card_created(adapter, chat_id, reply_to=reply_to, metadata=metadata)
    if not message_id:
        return None

    steps = _visible_tool_steps(adapter, chat_id)
    if not steps:
        return message_id

    now = asyncio.get_running_loop().time()
    if state.last_tool_status_update_at and (now - state.last_tool_status_update_at) < TOOL_STATUS_UPDATE_INTERVAL_SECONDS:
        return message_id
    state.last_tool_status_update_at = now

    card = build_streaming_pre_answer_card(
        tool_steps=steps,
        tool_elapsed_ms=get_tool_elapsed_ms(adapter, chat_id),
    )
    active_card_id = get_card_id(adapter, chat_id)
    if active_card_id:
        try:
            sequence = advance_card_sequence(adapter, chat_id)
            await update_card(adapter, card_id=active_card_id, card=card, sequence=sequence)
            return message_id
        except Exception as exc:
            if is_card_rate_limit_error(exc):
                return message_id
            logger.warning("hermes_feishu_plugin progress CardKit update failed: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)
            return message_id

    if not get_original_card_id(adapter, chat_id):
        await patch_interactive_card(adapter, message_id=message_id, card=card)
    return message_id


async def _finalize_card(adapter: Any, chat_id: str, text: str) -> bool:
    state = get_chat_state(adapter, chat_id)
    if state.phase == "completed":
        return True

    message_id = state.card_message_id
    if not message_id:
        return False

    state.phase = "completed"
    if state.flush_controller:
        state.flush_controller.complete()
        await state.flush_controller.wait_for_flush()

    complete_card = build_complete_card(
        text=text,
        tool_steps=_visible_tool_steps(adapter, chat_id),
        tool_elapsed_ms=get_tool_elapsed_ms(adapter, chat_id),
        elapsed_ms=_elapsed_ms(adapter, chat_id),
    )
    effective_card_id = get_card_id(adapter, chat_id) or get_original_card_id(adapter, chat_id)
    if effective_card_id:
        try:
            sequence = advance_card_sequence(adapter, chat_id)
            await set_card_streaming_mode(
                adapter,
                card_id=effective_card_id,
                streaming_mode=False,
                sequence=sequence,
            )
            sequence = advance_card_sequence(adapter, chat_id)
            await update_card(adapter, card_id=effective_card_id, card=to_cardkit2(complete_card), sequence=sequence)
            remember_display_text(adapter, chat_id, text)
            remember_last_flushed_text(adapter, chat_id, text)
            return True
        except Exception as exc:
            logger.warning("hermes_feishu_plugin final CardKit update failed; trying IM patch fallback: %s", exc)

    response = await patch_interactive_card(adapter, message_id=message_id, card=complete_card)
    if _response_ok(response):
        remember_display_text(adapter, chat_id, text)
        remember_last_flushed_text(adapter, chat_id, text)
        return True
    return False


def _strip_cursor(text: str, cursor: str) -> tuple[str, bool]:
    if cursor and text.endswith(cursor):
        return text[: -len(cursor)], False
    return text, True


def patch_streaming_cards() -> bool:
    """Patch Hermes stream consumer so Feishu uses CardKit-first streaming."""
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

        if not _is_feishu_adapter(self.adapter):
            return await original_send_or_edit(self, text)
        if not should_stream(self.adapter, self.chat_id):
            return await original_send_or_edit(self, text)

        if should_suppress_status_message(cleaned):
            lines = parse_tool_progress_lines(cleaned)
            if lines:
                remember_tool_steps(self.adapter, self.chat_id, lines)
                await sync_progress_card(self.adapter, self.chat_id, metadata=self.metadata)
            self._already_sent = True
            return

        if cleaned == self._last_sent_text:
            return

        visible_text, is_final = _strip_cursor(cleaned, self.cfg.cursor)
        try:
            message_id = await _ensure_card_created(
                self.adapter,
                self.chat_id,
                reply_to=_resolve_reply_to_message_id(self),
                metadata=self.metadata,
            )
            if not message_id:
                return await original_send_or_edit(self, text)

            self._message_id = message_id
            remember_display_text(self.adapter, self.chat_id, visible_text)
            if is_final:
                if not await _finalize_card(self.adapter, self.chat_id, visible_text):
                    return await original_send_or_edit(self, text)
            else:
                await _flush_answer(self.adapter, self.chat_id)

            self._already_sent = True
            self._last_sent_text = cleaned
        except Exception as exc:
            logger.warning("hermes_feishu_plugin CardKit streaming error: %s", exc)
            if not self._message_id:
                await original_send_or_edit(self, text)
            else:
                self._already_sent = True

    wrapped_send_or_edit.__hermes_feishu_plugin_wrapped__ = True
    stream_consumer.GatewayStreamConsumer._send_or_edit = wrapped_send_or_edit
    return True
