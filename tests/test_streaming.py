"""Regression tests for live streaming card updates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from hermes_feishu_plugin.card import streaming
from hermes_feishu_plugin.card.models import ToolDisplayStep
from hermes_feishu_plugin.channel.runtime_state import get_chat_state, remember_display_text, remember_tool_steps


class DummyAdapter:
    """Tiny adapter stub for streaming-progress tests."""


@pytest.mark.asyncio
async def test_sync_progress_card_keeps_visible_text_when_tool_status_refreshes(monkeypatch) -> None:
    """Tool-status refreshes should not blank out already streamed answer text."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-1")
    state.card_message_id = "om_card_1"
    state.card_id = "card_1"

    remember_display_text(adapter, "chat-1", "已输出的正文")
    remember_tool_steps(adapter, "chat-1", [ToolDisplayStep(title="Search docs", status="running")])

    captured: dict[str, object] = {}

    async def fake_update_card(_adapter, *, card_id: str, card: dict, sequence: int) -> None:
        captured["card_id"] = card_id
        captured["card"] = card
        captured["sequence"] = sequence

    monkeypatch.setattr(streaming, "update_card", fake_update_card)

    message_id = await streaming.sync_progress_card(adapter, "chat-1")

    assert message_id == "om_card_1"
    assert captured["card_id"] == "card_1"
    content_element = next(
        element
        for element in captured["card"]["body"]["elements"]
        if element.get("element_id") == streaming.STREAMING_ELEMENT_ID
    )
    assert content_element["content"] == "已输出的正文"


@pytest.mark.asyncio
async def test_finalize_card_keeps_streaming_phase_when_all_updates_fail(monkeypatch) -> None:
    """Finalize failure should keep the card retryable instead of marking it completed."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-finalize-fail")
    state.card_message_id = "om_card_1"
    state.card_id = "card_1"
    state.original_card_id = "card_1"
    state.phase = "streaming"

    async def fail_update_card(*_args, **_kwargs) -> None:
        raise RuntimeError("cardkit update failed")

    async def failed_patch_interactive_card(*_args, **_kwargs):
        return SimpleNamespace(success=lambda: False)

    monkeypatch.setattr(streaming, "set_card_streaming_mode", fail_update_card)
    monkeypatch.setattr(streaming, "update_card", fail_update_card)
    monkeypatch.setattr(streaming, "patch_interactive_card", failed_patch_interactive_card)

    finalized = await streaming._finalize_card(adapter, "chat-finalize-fail", "最终回答")

    assert finalized is False
    assert state.phase == "streaming"


@pytest.mark.asyncio
async def test_abort_progress_card_keeps_streaming_phase_when_all_updates_fail(monkeypatch) -> None:
    """Abort failure should keep the card retryable for the next inbound turn."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-abort-fail")
    state.card_message_id = "om_card_2"
    state.card_id = "card_2"
    state.original_card_id = "card_2"
    state.phase = "streaming"

    async def fail_update_card(*_args, **_kwargs) -> None:
        raise RuntimeError("cardkit update failed")

    async def failed_patch_interactive_card(*_args, **_kwargs):
        return SimpleNamespace(success=lambda: False)

    monkeypatch.setattr(streaming, "set_card_streaming_mode", fail_update_card)
    monkeypatch.setattr(streaming, "update_card", fail_update_card)
    monkeypatch.setattr(streaming, "patch_interactive_card", failed_patch_interactive_card)

    aborted = await streaming.abort_progress_card(adapter, "chat-abort-fail")

    assert aborted is False
    assert state.phase == "streaming"


@pytest.mark.asyncio
async def test_stream_consumer_run_finalizes_feishu_card_on_stream_end(monkeypatch) -> None:
    """Feishu wrapper must accept finalize-aware stream-consumer calls and close the live card."""
    from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig

    class FeishuAdapter:
        name = "feishu"
        MAX_MESSAGE_LENGTH = 4096

    adapter = FeishuAdapter()
    streaming.patch_streaming_cards()
    consumer = GatewayStreamConsumer(
        adapter,
        "chat-stream-end",
        StreamConsumerConfig(edit_interval=0.01, buffer_threshold=1, cursor=" ▉"),
    )
    state = get_chat_state(adapter, "chat-stream-end")
    state.card_message_id = "om_card_3"
    state.phase = "streaming"

    captured: dict[str, object] = {}

    monkeypatch.setattr(streaming, "should_stream", lambda *_args, **_kwargs: True)

    async def fake_ensure_card_created(*_args, **_kwargs) -> str:
        return "om_card_3"

    async def fake_finalize_card(_adapter, chat_id: str, text: str, *, expected_generation: int = 0) -> bool:
        captured["chat_id"] = chat_id
        captured["text"] = text
        captured["expected_generation"] = expected_generation
        get_chat_state(_adapter, chat_id).phase = "completed"
        return True

    async def fake_flush_answer(*_args, **_kwargs) -> None:
        captured["flushed"] = True

    monkeypatch.setattr(streaming, "_ensure_card_created", fake_ensure_card_created)
    monkeypatch.setattr(streaming, "_finalize_card", fake_finalize_card)
    monkeypatch.setattr(streaming, "_flush_answer", fake_flush_answer)

    task = asyncio.create_task(consumer.run())
    consumer.on_delta("这是最终正文")
    consumer.finish()
    await task

    assert captured["text"] == "这是最终正文"
    assert consumer.final_response_sent is True
    assert get_chat_state(adapter, "chat-stream-end").phase == "completed"
