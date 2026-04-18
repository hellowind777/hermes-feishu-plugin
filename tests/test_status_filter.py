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


def test_interrupt_status_does_not_leak_into_tool_progress_lines() -> None:
    """Busy-interrupt status should never be appended into Feishu tool steps."""
    text = "\n".join(
        [
            "[tool] vision_analyze(image)",
            "⚡ Interrupting current task (iteration 1/90). I'll respond to your message shortly.",
        ]
    )

    assert should_suppress_status_message(text.splitlines()[1]) is True
    assert parse_tool_progress_lines(text) == ["vision_analyze(image)"]
