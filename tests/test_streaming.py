"""Regression tests for live streaming card updates."""

from __future__ import annotations

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
