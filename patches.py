"""Runtime patches for the Hermes Feishu plugin."""

from __future__ import annotations

import asyncio
import base64
import http
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .i18n import approval_strings, localize_system_text, translate_approval_label
from .mode import should_stream
from .reaction import add_typing_reaction, clear_ack_reactions, remove_typing_reaction
from .runtime_state import (
    remember_inbound_message,
    remember_reply_target,
    remember_tool_steps,
)
from .state import get_reply_to_message_id, reset_reply_to_message_id, set_reply_to_message_id
from .status_filter import parse_tool_progress_lines, should_suppress_status_message
from .streaming import patch_streaming_cards, sync_progress_card

logger = logging.getLogger(__name__)

_PATCH_STATUS: dict[str, Any] = {
    "plugin_name": "hermes_feishu_plugin",
    "plugin_dir": str(Path(__file__).resolve().parent),
    "patched": {},
    "details": {},
}

_REPLY_TARGETS_ATTR = "_hermes_feishu_reply_targets"
_TYPING_REACTIONS_ATTR = "_hermes_feishu_typing_reactions"


def _extract_content_from_send_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if "content" in kwargs:
        return str(kwargs.get("content") or "")
    if len(args) >= 2:
        return str(args[1] or "")
    return ""


def _extract_content_from_edit_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if "content" in kwargs:
        return str(kwargs.get("content") or "")
    if len(args) >= 3:
        return str(args[2] or "")
    return ""


def _replace_send_content(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    content: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_kwargs = dict(kwargs)
    if "content" in new_kwargs:
        new_kwargs["content"] = content
        return args, new_kwargs
    if len(args) >= 2:
        new_args = list(args)
        new_args[1] = content
        return tuple(new_args), new_kwargs
    new_kwargs["content"] = content
    return args, new_kwargs


def _replace_edit_content(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    content: str,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    new_kwargs = dict(kwargs)
    if "content" in new_kwargs:
        new_kwargs["content"] = content
        return args, new_kwargs
    if len(args) >= 3:
        new_args = list(args)
        new_args[2] = content
        return tuple(new_args), new_kwargs
    new_kwargs["content"] = content
    return args, new_kwargs


async def _clear_ack_reactions_later(adapter: Any, message_id: str, delay: float) -> None:
    await asyncio.sleep(delay)
    await clear_ack_reactions(adapter, message_id)


def _ensure_runtime_state(adapter: Any) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    reply_targets = getattr(adapter, _REPLY_TARGETS_ATTR, None)
    if not isinstance(reply_targets, dict):
        reply_targets = {}
        setattr(adapter, _REPLY_TARGETS_ATTR, reply_targets)

    typing_reactions = getattr(adapter, _TYPING_REACTIONS_ATTR, None)
    if not isinstance(typing_reactions, dict):
        typing_reactions = {}
        setattr(adapter, _TYPING_REACTIONS_ATTR, typing_reactions)

    return reply_targets, typing_reactions


async def _maybe_handle_status_message(
    adapter: Any,
    *,
    chat_id: str,
    content: str,
    metadata: Any = None,
    message_id: str | None = None,
) -> Any | None:
    from gateway.platforms.base import SendResult

    tool_lines = parse_tool_progress_lines(content) if chat_id else []
    if tool_lines:
        remember_tool_steps(adapter, chat_id, tool_lines)
        if should_stream(adapter, chat_id):
            patched_id = await sync_progress_card(adapter, chat_id, metadata=metadata)
            return SendResult(success=True, message_id=patched_id or message_id)
        return SendResult(success=True, message_id=message_id)

    if should_suppress_status_message(content):
        return SendResult(success=True, message_id=message_id)
    return None


def patch_suppress_status_messages() -> bool:
    """Suppress Hermes-internal progress text so Feishu keeps one live card."""
    from gateway.platforms.feishu import FeishuAdapter

    original_send = FeishuAdapter.send
    if not getattr(original_send, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send(self: Any, *args, **kwargs):
            content = _extract_content_from_send_args(args, kwargs)
            chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
            handled = await _maybe_handle_status_message(
                self,
                chat_id=chat_id,
                content=content,
                metadata=kwargs.get("metadata"),
            )
            if handled is not None:
                return handled
            localized = localize_system_text(content)
            args, kwargs = _replace_send_content(args, kwargs, localized)
            return await original_send(self, *args, **kwargs)

        wrapped_send.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.send = wrapped_send

    original_edit = FeishuAdapter.edit_message
    if not getattr(original_edit, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_edit(self: Any, *args, **kwargs):
            content = _extract_content_from_edit_args(args, kwargs)
            chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
            message_id = str(kwargs.get("message_id") or (args[1] if len(args) >= 2 else "") or "").strip()
            handled = await _maybe_handle_status_message(
                self,
                chat_id=chat_id,
                content=content,
                message_id=message_id,
            )
            if handled is not None:
                return handled
            localized = localize_system_text(content)
            args, kwargs = _replace_edit_content(args, kwargs, localized)
            return await original_edit(self, *args, **kwargs)

        wrapped_edit.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.edit_message = wrapped_edit

    return True


def patch_feishu_websocket_card_callbacks() -> bool:
    """Patch Python lark_oapi WS client so CardKit/card action callbacks reach Hermes."""
    try:
        from lark_oapi.ws import client as ws_client_mod
    except Exception:
        return False

    original_handle_data_frame = ws_client_mod.Client._handle_data_frame
    if getattr(original_handle_data_frame, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_handle_data_frame(self: Any, frame: Any):
        headers = frame.headers
        type_ = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_TYPE)
        message_type = ws_client_mod.MessageType(type_)
        if message_type != ws_client_mod.MessageType.CARD:
            return await original_handle_data_frame(self, frame)

        msg_id = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_MESSAGE_ID)
        trace_id = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_TRACE_ID)
        sum_ = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_SUM)
        seq = ws_client_mod._get_by_key(headers, ws_client_mod.HEADER_SEQ)
        payload = frame.payload
        if int(sum_) > 1:
            payload = self._combine(msg_id, int(sum_), int(seq), payload)
            if payload is None:
                return

        response = ws_client_mod.Response(code=http.HTTPStatus.OK)
        try:
            started_at = int(round(time.time() * 1000))
            result = self._event_handler.do_without_validation(payload)
            finished_at = int(round(time.time() * 1000))
            header = headers.add()
            header.key = ws_client_mod.HEADER_BIZ_RT
            header.value = str(finished_at - started_at)
            if result is not None:
                response.data = base64.b64encode(ws_client_mod.JSON.marshal(result).encode(ws_client_mod.UTF_8))
        except Exception as exc:
            ws_client_mod.logger.error(
                self._fmt_log(
                    "handle message failed, message_type: {}, message_id: {}, trace_id: {}, err: {}",
                    message_type.value,
                    msg_id,
                    trace_id,
                    exc,
                )
            )
            response = ws_client_mod.Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = ws_client_mod.JSON.marshal(response).encode(ws_client_mod.UTF_8)
        await self._write_message(frame.SerializeToString())

    wrapped_handle_data_frame.__hermes_feishu_plugin_wrapped__ = True
    ws_client_mod.Client._handle_data_frame = wrapped_handle_data_frame
    return True


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


def patch_disable_ack_reaction() -> bool:
    """Disable Hermes' old persistent OK acknowledgement reaction."""
    from gateway.platforms.feishu import FeishuAdapter

    original_add_ack = FeishuAdapter._add_ack_reaction
    if getattr(original_add_ack, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_add_ack(self: Any, message_id: str):
        if message_id:
            await clear_ack_reactions(self, message_id)
        return None

    wrapped_add_ack.__hermes_feishu_plugin_wrapped__ = True
    FeishuAdapter._add_ack_reaction = wrapped_add_ack
    return True


def patch_typing_reaction() -> bool:
    """Use official-style transient Typing reaction while processing."""
    from gateway.platforms.feishu import FeishuAdapter

    original_guarded = FeishuAdapter._handle_message_with_guards
    original_send_typing = FeishuAdapter.send_typing
    original_stop_typing = FeishuAdapter.stop_typing

    if not getattr(original_send_typing, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send_typing(self: Any, chat_id: str, metadata=None) -> None:
            reply_targets, typing_reactions = _ensure_runtime_state(self)
            message_id = get_reply_to_message_id() or str(reply_targets.get(chat_id, "") or "").strip()
            if not message_id:
                return await original_send_typing(self, chat_id, metadata=metadata)

            active = typing_reactions.get(chat_id)
            if active and active[0] == message_id and active[1]:
                return None
            if active and active[0] and active[1]:
                await remove_typing_reaction(self, active[0], active[1])
                typing_reactions.pop(chat_id, None)

            await clear_ack_reactions(self, message_id)
            reaction_id = await add_typing_reaction(self, message_id)
            if reaction_id:
                typing_reactions[chat_id] = (message_id, reaction_id)
                reply_targets[chat_id] = message_id
                return None
            return await original_send_typing(self, chat_id, metadata=metadata)

        wrapped_send_typing.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.send_typing = wrapped_send_typing

    if not getattr(original_stop_typing, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_stop_typing(self: Any, chat_id: str) -> None:
            reply_targets, typing_reactions = _ensure_runtime_state(self)
            active = typing_reactions.pop(chat_id, None)
            if active and active[0] and active[1]:
                await remove_typing_reaction(self, active[0], active[1])
            current_target = str(reply_targets.get(chat_id, "") or "").strip()
            if not current_target or not active or current_target == active[0]:
                reply_targets.pop(chat_id, None)
            return await original_stop_typing(self, chat_id)

        wrapped_stop_typing.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.stop_typing = wrapped_stop_typing

    if getattr(original_guarded, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_guarded(self: Any, event: Any) -> None:
        source = getattr(event, "source", None)
        chat_id = getattr(source, "chat_id", "") or ""
        chat_lock = self._get_chat_lock(chat_id)
        message_id = getattr(event, "message_id", "") or ""
        chat_type = getattr(source, "chat_type", "dm") if source else "dm"
        reply_targets, _typing_reactions = _ensure_runtime_state(self)
        reply_token = set_reply_to_message_id(message_id)

        async with chat_lock:
            try:
                if message_id:
                    reply_targets[chat_id] = message_id
                    remember_reply_target(self, chat_id, message_id)
                    remember_inbound_message(self, chat_id, message_id, chat_type)
                    await clear_ack_reactions(self, message_id)
                    asyncio.create_task(_clear_ack_reactions_later(self, message_id, 1.0))
                await self.handle_message(event)
            finally:
                reset_reply_to_message_id(reply_token)
                if message_id:
                    await clear_ack_reactions(self, message_id)
                    asyncio.create_task(_clear_ack_reactions_later(self, message_id, 3.0))

    wrapped_guarded.__hermes_feishu_plugin_wrapped__ = True
    FeishuAdapter._handle_message_with_guards = wrapped_guarded
    return True


def apply_runtime_patches(*, plugin_name: str = "hermes_feishu_plugin") -> dict[str, Any]:
    """Apply all Feishu runtime patches idempotently."""
    _PATCH_STATUS["plugin_name"] = plugin_name
    patch_plan = (
        ("feishu_ws_card_callbacks", patch_feishu_websocket_card_callbacks, "Handle card.action.trigger WS frames instead of dropping them"),
        ("feishu_typing_reaction", patch_typing_reaction, "Use official-style transient Typing reaction"),
        ("feishu_disable_ack_reaction", patch_disable_ack_reaction, "Disable persistent OK acknowledgement reaction"),
        ("feishu_suppress_status_messages", patch_suppress_status_messages, "Suppress progress/status noise and route progress into the live card"),
        ("feishu_exec_approval_localization", patch_exec_approval_localization, "Localize approval cards and callbacks"),
        ("feishu_streaming_cards", patch_streaming_cards, "Use CardKit-first single-card streaming with IM patch fallback"),
    )
    for key, patch_fn, detail in patch_plan:
        try:
            ok = patch_fn()
            _PATCH_STATUS["patched"][key] = bool(ok)
            _PATCH_STATUS["details"][key] = detail if ok else "not applied"
        except Exception as exc:
            _PATCH_STATUS["patched"][key] = False
            _PATCH_STATUS["details"][key] = f"deferred: {exc}"
            logger.debug("hermes_feishu_plugin deferred %s: %s", key, exc)
    return get_patch_status()


def get_patch_status() -> dict[str, Any]:
    """Return patch status for diagnostics."""
    return {
        "plugin_name": _PATCH_STATUS["plugin_name"],
        "plugin_dir": _PATCH_STATUS["plugin_dir"],
        "patched": dict(_PATCH_STATUS["patched"]),
        "details": dict(_PATCH_STATUS["details"]),
    }
