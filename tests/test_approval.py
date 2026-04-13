"""Tests for approval-card callback recovery."""

from __future__ import annotations

import itertools
import json
import sys
import types
from types import SimpleNamespace

import pytest

from hermes_feishu_plugin.channel import approval as approval_module


def _install_fake_gateway_modules(monkeypatch):
    class SendResult:
        """Minimal SendResult shim."""

        def __init__(self, *, success: bool, error: str = "", message_id: str = "") -> None:
            self.success = success
            self.error = error
            self.message_id = message_id

    class FeishuAdapter:
        """Minimal adapter stub used by approval patch tests."""

        def __init__(self) -> None:
            self._client = object()
            self._approval_counter = itertools.count(1)
            self._approval_state: dict[str, dict[str, str]] = {}
            self.sent_payload: dict[str, object] | None = None
            self.original_action_called = False

        async def send_exec_approval(self, *args, **kwargs):
            return None

        async def _update_approval_card(self, *args, **kwargs):
            return None

        async def _handle_card_action_event(self, *args, **kwargs):
            self.original_action_called = True
            return None

        async def _feishu_send_with_retry(self, *, payload: str, **kwargs):
            self.sent_payload = json.loads(payload)
            return SimpleNamespace()

        def _finalize_send_result(self, response, error_message: str):
            return SimpleNamespace(success=True, message_id="om_approval_1")

        def _is_card_action_duplicate(self, token: str) -> bool:
            return False

        async def _resolve_sender_profile(self, sender) -> dict[str, str]:
            return {"user_name": "测试用户"}

    gateway_mod = types.ModuleType("gateway")
    platforms_mod = types.ModuleType("gateway.platforms")
    base_mod = types.ModuleType("gateway.platforms.base")
    feishu_mod = types.ModuleType("gateway.platforms.feishu")

    base_mod.SendResult = SendResult
    feishu_mod.FeishuAdapter = FeishuAdapter
    gateway_mod.platforms = platforms_mod
    platforms_mod.base = base_mod
    platforms_mod.feishu = feishu_mod

    monkeypatch.setitem(sys.modules, "gateway", gateway_mod)
    monkeypatch.setitem(sys.modules, "gateway.platforms", platforms_mod)
    monkeypatch.setitem(sys.modules, "gateway.platforms.base", base_mod)
    monkeypatch.setitem(sys.modules, "gateway.platforms.feishu", feishu_mod)
    return FeishuAdapter


@pytest.mark.asyncio
async def test_send_exec_approval_embeds_recoverable_callback_context(monkeypatch) -> None:
    """Approval buttons should carry enough context to recover after restarts."""
    feishu_adapter = _install_fake_gateway_modules(monkeypatch)

    assert approval_module.patch_exec_approval_localization() is True

    adapter = feishu_adapter()
    await adapter.send_exec_approval(
        "oc_chat_1",
        "sudo reboot",
        "session-1",
        "dangerous command",
    )

    assert adapter.sent_payload is not None
    action_values = adapter.sent_payload["elements"][1]["actions"]
    button_value = action_values[0]["value"]

    assert button_value["approval_id"] == "1"
    assert button_value["session_key"] == "session-1"
    assert button_value["chat_id"] == "oc_chat_1"


@pytest.mark.asyncio
async def test_approval_callback_recovers_without_in_memory_state(monkeypatch) -> None:
    """Approval callbacks should still resolve and refresh the card after state loss."""
    feishu_adapter = _install_fake_gateway_modules(monkeypatch)

    tools_mod = types.ModuleType("tools")
    approval_tools_mod = types.ModuleType("tools.approval")
    resolved: dict[str, object] = {}

    def resolve_gateway_approval(session_key: str, choice: str) -> int:
        resolved["session_key"] = session_key
        resolved["choice"] = choice
        return 1

    approval_tools_mod.resolve_gateway_approval = resolve_gateway_approval
    tools_mod.approval = approval_tools_mod
    monkeypatch.setitem(sys.modules, "tools", tools_mod)
    monkeypatch.setitem(sys.modules, "tools.approval", approval_tools_mod)

    assert approval_module.patch_exec_approval_localization() is True

    adapter = feishu_adapter()
    await adapter.send_exec_approval(
        "oc_chat_1",
        "sudo reboot",
        "session-1",
        "dangerous command",
    )
    button_value = adapter.sent_payload["elements"][1]["actions"][1]["value"]
    adapter._approval_state.clear()

    updated: dict[str, str] = {}

    async def fake_update(message_id: str, label: str, user_name: str, choice: str) -> None:
        updated["message_id"] = message_id
        updated["label"] = label
        updated["user_name"] = user_name
        updated["choice"] = choice

    adapter._update_approval_card = fake_update

    data = SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(value=button_value),
            token="token-1",
            context=SimpleNamespace(open_chat_id="oc_chat_1", open_message_id="om_approval_1:approval"),
            operator=SimpleNamespace(open_id="ou_test"),
        )
    )

    await adapter._handle_card_action_event(data)

    assert resolved == {"session_key": "session-1", "choice": "session"}
    assert updated["message_id"] == "om_approval_1"
    assert updated["choice"] == "session"
    assert updated["user_name"] == "测试用户"
