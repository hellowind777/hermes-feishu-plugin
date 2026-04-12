"""Tests for status-message filtering."""

from __future__ import annotations

from hermes_feishu_plugin.channel.status_filter import (
    is_model_switch_status_message,
    parse_tool_progress_lines,
    should_suppress_status_message,
)


def test_localized_model_switch_status_is_not_treated_as_tool_progress() -> None:
    """Localized fallback notices should stay in the status area."""
    text = "🔄 已切换到第 1 备用 API 渠道：codexzh（gpt-5.4，codex_responses）"

    assert is_model_switch_status_message(text) is True
    assert should_suppress_status_message(text) is True
    assert parse_tool_progress_lines(text) == []
