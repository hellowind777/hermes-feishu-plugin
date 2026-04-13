"""Tests for 10-minute in-card heartbeat notices."""

from __future__ import annotations

from unittest.mock import patch

from hermes_feishu_plugin.card.heartbeat import refresh_heartbeat_status
from hermes_feishu_plugin.channel.runtime_state import (
    get_chat_state,
    get_heartbeat_status_text,
    note_visible_activity,
)


class DummyAdapter:
    """Tiny adapter stub for heartbeat tests."""


def test_heartbeat_notice_appears_after_ten_minutes_of_no_progress() -> None:
    """Heartbeat text should appear in 10-minute buckets after visible progress stalls."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-1")
    state.started_at = 100.0
    state.last_visible_activity_at = 100.0

    with patch("hermes_feishu_plugin.card.heartbeat.time.monotonic", return_value=701.0):
        changed = refresh_heartbeat_status(adapter, "chat-1")

    assert changed is True
    assert "10 分钟无新进展" in get_heartbeat_status_text(adapter, "chat-1")


def test_heartbeat_notice_clears_after_new_progress() -> None:
    """Any visible progress should immediately clear the stale heartbeat note."""
    adapter = DummyAdapter()
    state = get_chat_state(adapter, "chat-1")
    state.heartbeat_status_text = "仍在处理中 · 最近 10 分钟无新进展"

    note_visible_activity(adapter, "chat-1")

    assert get_heartbeat_status_text(adapter, "chat-1") == ""
