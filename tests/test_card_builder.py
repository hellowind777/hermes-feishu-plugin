"""Tests for CardKit builders and reasoning extraction helpers."""

from __future__ import annotations

from hermes_feishu_plugin.card.builder import (
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_patch_card,
    build_streaming_pre_answer_card,
    split_reasoning_text,
)
from hermes_feishu_plugin.card.live_state import should_show_tool_use
from hermes_feishu_plugin.card.models import ToolDisplayStep
from hermes_feishu_plugin.channel.runtime_state import remember_tool_steps


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


def test_build_streaming_pre_answer_card_can_render_status_text() -> None:
    """Pre-answer cards should show provider-switch status in the content area."""
    card = build_streaming_pre_answer_card(status_text="已切换到第 1 备用 API 渠道：codexzh")

    content_element = next(element for element in card["body"]["elements"] if element.get("element_id") == STREAMING_ELEMENT_ID)

    assert content_element["content"] == "已切换到第 1 备用 API 渠道：codexzh"


def test_build_streaming_pre_answer_card_can_render_heartbeat_text() -> None:
    """Heartbeat text should stay in a dedicated status area, not overwrite answer text."""
    card = build_streaming_pre_answer_card(
        text="已有正文",
        heartbeat_text="仍在处理中 · 最近 10 分钟无新进展",
    )

    heartbeat_element = next(element for element in card["body"]["elements"] if element.get("element_id") == "heartbeat_status")
    content_element = next(element for element in card["body"]["elements"] if element.get("element_id") == STREAMING_ELEMENT_ID)

    assert content_element["content"] == "已有正文"
    assert heartbeat_element["content"] == "仍在处理中 · 最近 10 分钟无新进展"


def test_build_streaming_pre_answer_card_preserves_streamed_text_during_progress_updates() -> None:
    """Progress refreshes should keep the already streamed visible text."""
    card = build_streaming_pre_answer_card(
        text="这段内容已经吐出来了",
        status_text="已切换到备用渠道",
    )

    content_element = next(element for element in card["body"]["elements"] if element.get("element_id") == STREAMING_ELEMENT_ID)

    assert content_element["content"] == "这段内容已经吐出来了"


def test_streaming_tool_panels_default_to_collapsed() -> None:
    """Live tool panels should stay collapsed unless the user opens them."""
    steps = [ToolDisplayStep(title="Run command", status="running")]

    pre_answer = build_streaming_pre_answer_card(tool_steps=steps, show_tool_use=True)
    assert pre_answer["body"]["elements"][0]["expanded"] is False

    patch_card = build_streaming_patch_card(tool_steps=steps, show_tool_use=True)
    assert patch_card["elements"][0]["expanded"] is False


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


def test_show_tool_use_only_after_real_tool_steps() -> None:
    """Runtime should hide the tool panel until a tool step actually exists."""
    class DummyAdapter:
        """Minimal adapter stub."""

    adapter = DummyAdapter()

    assert should_show_tool_use(adapter, "chat-1") is False

    remember_tool_steps(adapter, "chat-1", ["🔎 find *.py"])

    assert should_show_tool_use(adapter, "chat-1") is True
