"""Tests for Feishu status-message filtering and localization."""

from __future__ import annotations

from hermes_feishu_plugin.channel.status_filter import is_model_switch_status_message, should_suppress_status_message
from hermes_feishu_plugin.core.i18n import localize_system_text


def test_model_switch_status_messages_are_suppressed_from_plain_chat(monkeypatch) -> None:
    """Provider switch lifecycle messages should not leak as separate chat text."""
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")
    messages = [
        "⚠️ Rate limited — switching to fallback provider...",
        "🔄 Primary model failed — switching to fallback: gpt-5.4 via custom",
        "⚠️ Non-retryable error (HTTP 404) — trying fallback...",
        "⚠️ Max retries (3) exhausted — trying fallback...",
    ]

    for message in messages:
        assert is_model_switch_status_message(message)
        assert should_suppress_status_message(message)


def test_localize_model_switch_status_text(monkeypatch) -> None:
    """Fixed provider-switch phrases should follow the configured locale."""
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")

    localized = localize_system_text("⚠️ Rate limited — switching to fallback provider...")

    assert "主 API 渠道触发限速" in localized
