"""Approval-card localization patches."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

from ..core.i18n import approval_strings, localize_system_text, translate_approval_label

logger = logging.getLogger(__name__)


def _approval_state_keys(raw_value: Any) -> list[Any]:
    keys: list[Any] = []

    def add(candidate: Any) -> None:
        if candidate is not None and candidate not in keys:
            keys.append(candidate)

    add(raw_value)
    text = str(raw_value or "").strip()
    if text:
        add(text)
        if text.isdigit():
            add(int(text))
    return keys


def _pop_approval_state(adapter: Any, approval_id: Any, chat_id: str) -> tuple[Any | None, dict[str, str] | None]:
    for key in _approval_state_keys(approval_id):
        if key in adapter._approval_state:
            return key, adapter._approval_state.pop(key, None)

    matches = [
        (key, value)
        for key, value in list(adapter._approval_state.items())
        if str((value or {}).get("chat_id", "") or "").strip() == chat_id
    ]
    if len(matches) == 1:
        key, value = matches[0]
        adapter._approval_state.pop(key, None)
        return key, value
    return None, None


def patch_exec_approval_localization() -> bool:
    """Localize approval cards and tolerate callback payload differences."""
    from gateway.platforms.base import SendResult
    from gateway.platforms.feishu import FeishuAdapter

    original_send_exec = FeishuAdapter.send_exec_approval
    if not getattr(original_send_exec, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send_exec(
            self: Any,
            chat_id: str,
            command: str,
            session_key: str,
            description: str = "dangerous command",
            metadata: dict[str, Any] | None = None,
        ) -> Any:
            if not self._client:
                return SendResult(success=False, error="Not connected")

            strings = approval_strings()
            approval_id = str(next(self._approval_counter))
            cmd_preview = command[:3000] + "..." if len(command) > 3000 else command

            def btn(label: str, action_name: str, btn_type: str = "default") -> dict[str, Any]:
                return {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": btn_type,
                    "value": {"hermes_action": action_name, "approval_id": approval_id},
                }

            card = {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"content": strings["title"], "tag": "plain_text"}, "template": "orange"},
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"```\n{cmd_preview}\n```\n**{strings['reason_label']}：** {localize_system_text(description)}\n\n{strings['fallback_hint']}",
                    },
                    {
                        "tag": "action",
                        "actions": [
                            btn(strings["allow_once"], "approve_once", "primary"),
                            btn(strings["allow_session"], "approve_session"),
                            btn(strings["allow_always"], "approve_always"),
                            btn(strings["deny"], "deny", "danger"),
                        ],
                    },
                ],
            }
            response = await self._feishu_send_with_retry(
                chat_id=chat_id,
                msg_type="interactive",
                payload=json.dumps(card, ensure_ascii=False),
                reply_to=None,
                metadata=metadata,
            )
            result = self._finalize_send_result(response, "send_exec_approval failed")
            if result.success:
                self._approval_state[approval_id] = {
                    "session_key": session_key,
                    "message_id": result.message_id or "",
                    "chat_id": chat_id,
                }
            return result

        wrapped_send_exec.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.send_exec_approval = wrapped_send_exec

    original_update_card = FeishuAdapter._update_approval_card
    if not getattr(original_update_card, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_update_card(self: Any, message_id: str, label: str, user_name: str, choice: str) -> None:
            if not self._client or not message_id:
                return
            icon = "❌" if choice == "deny" else "✅"
            localized_label = translate_approval_label(label)
            strings = approval_strings()
            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"content": f"{icon} {localized_label}", "tag": "plain_text"},
                    "template": "red" if choice == "deny" else "green",
                },
                "elements": [{"tag": "markdown", "content": f"{icon} **{localized_label}** · {strings['by_user']}：{user_name}"}],
            }
            payload = json.dumps(card, ensure_ascii=False)
            body = self._build_update_message_body(msg_type="interactive", content=payload)
            request = self._build_update_message_request(message_id=message_id, request_body=body)
            await asyncio.to_thread(self._client.im.v1.message.update, request)

        wrapped_update_card.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter._update_approval_card = wrapped_update_card

    original_handle_action = FeishuAdapter._handle_card_action_event
    if getattr(original_handle_action, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_handle_action(self: Any, data: Any) -> None:
        event = getattr(data, "event", None)
        action = getattr(event, "action", None)
        action_value = getattr(action, "value", {}) or {}
        hermes_action = action_value.get("hermes_action") if isinstance(action_value, dict) else None
        if not hermes_action:
            return await original_handle_action(self, data)

        token = str(getattr(event, "token", "") or "")
        if token and self._is_card_action_duplicate(token):
            return

        context = getattr(event, "context", None)
        chat_id = str(getattr(context, "open_chat_id", "") or getattr(context, "chat_id", "") or "")
        matched_key, state = _pop_approval_state(self, action_value.get("approval_id"), chat_id)
        if not state:
            logger.warning("[Feishu] Approval state not found: raw_id=%r chat_id=%s", action_value.get("approval_id"), chat_id)
            return

        choice_map = {
            "approve_once": "once",
            "approve_session": "session",
            "approve_always": "always",
            "deny": "deny",
        }
        choice = choice_map.get(hermes_action, "deny")
        strings = approval_strings()
        label = {
            "once": strings["approved_once"],
            "session": strings["approved_session"],
            "always": strings["approved_always"],
            "deny": strings["denied"],
        }.get(choice, strings["resolved"])

        operator = getattr(event, "operator", None)
        open_id = str(getattr(operator, "open_id", "") or "")
        user_id = str(getattr(operator, "user_id", "") or "")
        union_id = str(getattr(operator, "union_id", "") or "")
        sender_profile: dict[str, Any] = {}
        if open_id or user_id or union_id:
            try:
                sender_profile = await self._resolve_sender_profile(
                    SimpleNamespace(open_id=open_id or None, user_id=user_id or None, union_id=union_id or None)
                )
            except Exception as exc:
                logger.debug("[Feishu] Failed to resolve approval sender: %s", exc)
        user_name = sender_profile.get("user_name") or open_id or user_id or union_id or strings["unknown_user"]

        try:
            from tools.approval import resolve_gateway_approval

            count = resolve_gateway_approval(state["session_key"], choice)
            logger.info("[Feishu] Approval resolved: matched=%r session=%s choice=%s count=%d", matched_key, state["session_key"], choice, count)
        except Exception as exc:
            logger.error("Failed to resolve gateway approval from Feishu button: %s", exc)

        await self._update_approval_card(state.get("message_id", ""), label, user_name, choice)

    wrapped_handle_action.__hermes_feishu_plugin_wrapped__ = True
    FeishuAdapter._handle_card_action_event = wrapped_handle_action
    return True
