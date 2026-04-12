"""Tests for Feishu status-patch routing."""

from __future__ import annotations

import pytest

from hermes_feishu_plugin.channel import status_patches
from hermes_feishu_plugin.channel.runtime_state import (
    get_chat_state,
    get_fallback_tool_lines,
    get_pending_status_text,
    get_tool_steps,
)


class DummyAdapter:
    """Tiny adapter stub for status-patch tests."""


@pytest.mark.asyncio
async def test_model_switch_status_updates_pending_status_text(monkeypatch) -> None:
    """Provider fallback notices should render as status text, not tool steps."""
    adapter = DummyAdapter()

    monkeypatch.setattr(status_patches, "should_stream", lambda _adapter, _chat_id: True)

    captured: dict[str, str] = {}

    async def fake_sync_progress_card(_adapter, chat_id: str, metadata=None):
        captured["chat_id"] = chat_id
        return "om_card_1"

    monkeypatch.setattr(status_patches, "sync_progress_card", fake_sync_progress_card)

    result = await status_patches.maybe_handle_status_message(
        adapter,
        chat_id="chat-1",
        content="⚠️ Rate limited — switching to fallback provider...",
    )

    assert captured["chat_id"] == "chat-1"
    assert "主 API 渠道触发限速" in get_pending_status_text(adapter, "chat-1")
    assert get_tool_steps(adapter, "chat-1") == []
    assert get_fallback_tool_lines(adapter, "chat-1") == []
    assert getattr(result, "message_id", "") == "om_card_1"


@pytest.mark.asyncio
async def test_non_stream_final_reply_is_folded_back_into_existing_card(monkeypatch) -> None:
    """When streaming produced a live card, final plain text should close that card."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-1")
    state.card_message_id = "om_card_1"
    state.phase = "streaming"

    monkeypatch.setattr(status_patches, "should_stream", lambda _adapter, _chat_id: True)

    captured: dict[str, str] = {}

    async def fake_finalize_progress_card(_adapter, chat_id: str, text: str) -> bool:
        captured["chat_id"] = chat_id
        captured["text"] = text
        return True

    monkeypatch.setattr(status_patches, "finalize_progress_card", fake_finalize_progress_card)

    result = await status_patches.maybe_handle_final_response(
        adapter,
        chat_id="chat-1",
        content="你的？",
    )

    assert captured == {"chat_id": "chat-1", "text": "你的？"}
    assert getattr(result, "message_id", "") == "om_card_1"
