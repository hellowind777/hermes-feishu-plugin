"""Tests for CardKit builders and reasoning extraction helpers."""

from __future__ import annotations

from hermes_feishu_plugin.card.builder import (
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_pre_answer_card,
    split_reasoning_text,
)
from hermes_feishu_plugin.card.models import ToolDisplayStep


def test_split_reasoning_text_extracts_xml_reasoning_and_answer() -> None:
    """XML-style think tags should become hidden reasoning plus visible answer."""
    reasoning, answer = split_reasoning_text("<think>step 1\nstep 2</think>\nFinal answer")

    assert reasoning == "step 1\nstep 2"
    assert answer == "Final answer"


def test_split_reasoning_text_cleans_reasoning_prefix_blocks() -> None:
    """Reasoning-prefixed responses should stay in the reasoning panel only."""
    reasoning, answer = split_reasoning_text("Reasoning:\n_plan_\nnext action")

    assert reasoning == "plan\nnext action"
    assert answer == ""


def test_build_streaming_pre_answer_card_uses_cardkit_streaming_shape() -> None:
    """Pre-answer streaming cards should expose OpenClaw-style CardKit markers."""
    card = build_streaming_pre_answer_card()

    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    assert card["config"]["summary"]["i18n_content"]["zh_cn"] == "处理中..."
    elements = card["body"]["elements"]
    assert elements[0]["tag"] == "collapsible_panel"
    assert any(element.get("element_id") == STREAMING_ELEMENT_ID for element in elements)
    assert any(element.get("element_id") == "loading_icon" for element in elements)


def test_card_builder_uses_preferred_locale_for_visible_labels(monkeypatch) -> None:
    """Visible card labels should follow the detected system locale."""
    monkeypatch.setenv("HERMES_FEISHU_LOCALE", "zh_cn")

    streaming = build_streaming_pre_answer_card()
    streaming_header = streaming["body"]["elements"][0]["header"]["title"]
    assert streaming["config"]["summary"]["content"] == "处理中..."
    assert streaming_header["content"] == "🛠️ 等待工具执行"

    complete = build_complete_card(
        text="done",
        tool_steps=[ToolDisplayStep(title="Run command", status="running")],
        tool_elapsed_ms=1800,
        elapsed_ms=2500,
    )
    tool_panel_header = complete["elements"][0]["header"]["title"]
    footer = complete["elements"][-1]

    assert tool_panel_header["content"].startswith("🛠️ 工具执行")
    assert "已完成" in footer["content"]
