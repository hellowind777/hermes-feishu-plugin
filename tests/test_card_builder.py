"""Tests for CardKit builders and reasoning extraction helpers."""

from __future__ import annotations

from hermes_feishu_plugin.card.builder import STREAMING_ELEMENT_ID, build_streaming_pre_answer_card, split_reasoning_text


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
