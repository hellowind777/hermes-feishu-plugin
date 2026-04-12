"""Tests for structured tool-use step rendering helpers."""

from __future__ import annotations

from hermes_feishu_plugin.card.tool_display import record_tool_finish, record_tool_start
from hermes_feishu_plugin.channel.runtime_state import get_chat_state


class _Adapter:
    """Minimal adapter object used by runtime-state helpers."""


def test_record_tool_start_and_finish_builds_structured_success_step() -> None:
    """A normal tool lifecycle should yield a completed structured step."""
    adapter = _Adapter()

    record_tool_start(
        adapter,
        "chat-success",
        tool_name="read",
        args={"path": "/tmp/reports/demo.txt"},
        task_id="task-1",
    )
    state = get_chat_state(adapter, "chat-success")
    assert len(state.tool_steps) == 1
    assert state.tool_steps[0].title == "Read"
    assert state.tool_steps[0].detail == "demo.txt"
    assert state.tool_steps[0].status == "running"

    record_tool_finish(
        adapter,
        "chat-success",
        tool_name="read",
        args={"path": "/tmp/reports/demo.txt"},
        result='{"result":{"matched":3,"file":"demo.txt"}}',
        task_id="task-1",
    )

    step = get_chat_state(adapter, "chat-success").tool_steps[0]
    assert step.status == "success"
    assert step.result_block is not None
    assert step.result_block.language == "json"
    assert '"matched": 3' in step.result_block.content
    assert get_chat_state(adapter, "chat-success").tool_elapsed_ms >= 0


def test_record_tool_finish_creates_missing_step_and_redacts_inline_secrets() -> None:
    """Late tool completion should backfill a step and hide command secrets."""
    adapter = _Adapter()

    record_tool_finish(
        adapter,
        "chat-error",
        tool_name="exec",
        args={"command": "token=abc password=def"},
        result="Error: command failed",
        task_id="task-2",
    )

    step = get_chat_state(adapter, "chat-error").tool_steps[0]
    assert step.title == "Run command"
    assert step.detail == "token=[redacted] password=[redacted]"
    assert step.status == "error"
    assert step.error_block is not None
    assert "Error: command failed" in step.error_block.content
