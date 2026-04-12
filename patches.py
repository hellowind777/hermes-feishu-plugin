"""Runtime patches for the Hermes Feishu plugin."""

from __future__ import annotations

import asyncio
import base64
import http
import json
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .i18n import approval_strings, localize_system_text, translate_approval_label
from .mode import should_stream
from .reaction import add_typing_reaction, clear_ack_reactions, remove_typing_reaction
from .runtime_state import (
    get_registered_adapter,
    get_registered_loop,
    remember_inbound_message,
    remember_reply_target,
    remember_tool_steps,
)
from .status_filter import should_suppress_status_message
from .status_filter import is_tool_progress_block, parse_tool_progress_lines
from .state import get_reply_to_message_id, reset_reply_to_message_id, set_reply_to_message_id
from .streaming import patch_streaming_cards, sync_progress_card

logger = logging.getLogger(__name__)

_PATCH_STATUS: dict[str, Any] = {
    "plugin_name": "hermes_feishu_plugin",
    "plugin_dir": str(Path(__file__).resolve().parent),
    "patched": {
        "feishu_typing_reaction": False,
        "feishu_disable_ack_reaction": False,
        "feishu_suppress_status_messages": False,
        "feishu_streaming_cards": False,
        "feishu_ws_card_callbacks": False,
    },
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


def patch_suppress_status_messages() -> bool:
    from gateway.platforms.base import SendResult
    from gateway.platforms.feishu import FeishuAdapter

    original_send = FeishuAdapter.send
    if not getattr(original_send, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send(self: Any, *args, **kwargs):
            content = _extract_content_from_send_args(args, kwargs)
            chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
            metadata = kwargs.get("metadata")
            tool_steps = parse_tool_progress_lines(content) if chat_id else []
            if tool_steps:
                remember_tool_steps(self, chat_id, tool_steps)
                if should_stream(self, chat_id):
                    message_id = await sync_progress_card(self, chat_id, metadata=metadata)
                    return SendResult(success=True, message_id=message_id)
                return SendResult(success=True)
            if should_suppress_status_message(content):
                logger.info(
                    "hermes_feishu_plugin suppressed Feishu status send: %s",
                    content.splitlines()[0][:160],
                )
                return SendResult(success=True)
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
            message_id = kwargs.get("message_id") or (args[1] if len(args) >= 2 else None)
            tool_steps = parse_tool_progress_lines(content) if chat_id else []
            if tool_steps:
                remember_tool_steps(self, chat_id, tool_steps)
                if should_stream(self, chat_id):
                    patched_id = await sync_progress_card(self, chat_id)
                    return SendResult(success=True, message_id=patched_id or message_id)
                return SendResult(success=True, message_id=message_id)
            if should_suppress_status_message(content):
                logger.info(
                    "hermes_feishu_plugin suppressed Feishu status edit: %s",
                    content.splitlines()[0][:160],
                )
                return SendResult(success=True, message_id=message_id)
            localized = localize_system_text(content)
            args, kwargs = _replace_edit_content(args, kwargs, localized)
            return await original_edit(self, *args, **kwargs)

        wrapped_edit.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter.edit_message = wrapped_edit

    return True


def patch_subagent_progress_relay() -> bool:
    from tools import delegate_tool

    original_build = delegate_tool._build_child_progress_callback
    if getattr(original_build, "__hermes_feishu_plugin_wrapped__", False):
        return True

    def wrapped_build(task_index: int, parent_agent: Any, task_count: int = 1):
        spinner = getattr(parent_agent, "_delegate_spinner", None)
        parent_cb = getattr(parent_agent, "tool_progress_callback", None)

        if not spinner and not parent_cb:
            return None

        prefix = f"[{task_index + 1}] " if task_count > 1 else ""
        relay_label = f"子代理{task_index + 1}" if task_count > 1 else "子代理"

        def _push_progress_direct(tool_name: str | None, preview: str | None) -> None:
            chat_id = str(os.getenv("HERMES_SESSION_CHAT_ID", "") or "").strip()
            if not chat_id:
                return
            adapter = get_registered_adapter(chat_id)
            loop = get_registered_loop(chat_id)
            if not adapter or not loop or not should_stream(adapter, chat_id):
                return

            from agent.display import get_tool_emoji

            emoji = get_tool_emoji(tool_name or "", default="⚙️")
            line = f"{emoji} {tool_name or 'subagent'}"
            if preview:
                line += f': "{preview}"'

            async def _apply() -> None:
                remember_tool_steps(adapter, chat_id, [line])
                await sync_progress_card(adapter, chat_id)

            try:
                asyncio.run_coroutine_threadsafe(_apply(), loop)
            except Exception as exc:
                logger.debug("Direct subagent card relay failed: %s", exc)

        def _relay_to_parent(tool_name: str | None, preview: str | None, args: Any) -> None:
            if not parent_cb:
                return
            relay_preview = str(preview or "").strip()
            if relay_preview:
                relay_preview = f"{relay_label} · {relay_preview}"
            else:
                relay_preview = relay_label
            try:
                parent_cb(
                    "tool.started",
                    tool_name or "subagent",
                    relay_preview,
                    args if isinstance(args, dict) else {"source": "subagent", "task_index": task_index + 1},
                )
            except Exception as exc:
                logger.debug("Parent callback failed for subagent relay: %s", exc)

        def _callback(event_type: str, tool_name: str = None, preview: str = None, args=None, **kwargs):
            if event_type in ("_thinking", "reasoning.available"):
                text = str(preview or tool_name or "").strip()
                if spinner and text:
                    short = (text[:55] + "...") if len(text) > 55 else text
                    try:
                        spinner.print_above(f" {prefix}├─ 💭 \"{short}\"")
                    except Exception as exc:
                        logger.debug("Spinner print_above failed: %s", exc)
                return

            if event_type == "tool.completed":
                return

            if spinner:
                short = (preview[:35] + "...") if preview and len(preview) > 35 else (preview or "")
                from agent.display import get_tool_emoji
                emoji = get_tool_emoji(tool_name or "")
                line = f" {prefix}├─ {emoji} {tool_name}"
                if short:
                    line += f"  \"{short}\""
                try:
                    spinner.print_above(line)
                except Exception as exc:
                    logger.debug("Spinner print_above failed: %s", exc)

            _push_progress_direct(tool_name, preview)
            _relay_to_parent(tool_name, preview, args)

        return _callback

    wrapped_build.__hermes_feishu_plugin_wrapped__ = True
    delegate_tool._build_child_progress_callback = wrapped_build
    return True


def patch_feishu_websocket_card_callbacks() -> bool:
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

        ws_client_mod.logger.debug(
            self._fmt_log(
                "receive message, message_type: {}, message_id: {}, trace_id: {}, payload: {}",
                message_type.value,
                msg_id,
                trace_id,
                payload.decode(ws_client_mod.UTF_8),
            )
        )

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

    def _add(candidate: Any) -> None:
        if candidate is None:
            return
        if candidate not in keys:
            keys.append(candidate)

    _add(raw_value)
    text = str(raw_value or "").strip()
    if text:
        _add(text)
        if text.isdigit():
            try:
                _add(int(text))
            except ValueError:
                pass
    return keys


def _pop_approval_state(adapter: Any, approval_id: Any, chat_id: str) -> tuple[Any | None, dict[str, str] | None]:
    for key in _approval_state_keys(approval_id):
        if key in adapter._approval_state:
            return key, adapter._approval_state.pop(key, None)

    if chat_id:
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

            try:
                strings = approval_strings()
                approval_id = str(next(self._approval_counter))
                cmd_preview = command[:3000] + "..." if len(command) > 3000 else command

                def _btn(label: str, action_name: str, btn_type: str = "default") -> dict[str, Any]:
                    return {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": btn_type,
                        "value": {"hermes_action": action_name, "approval_id": approval_id},
                    }

                description_text = localize_system_text(description)
                card = {
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"content": strings["title"], "tag": "plain_text"},
                        "template": "orange",
                    },
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"```\n{cmd_preview}\n```\n**{strings['reason_label']}：** {description_text}\n\n{strings['fallback_hint']}",
                        },
                        {
                            "tag": "action",
                            "actions": [
                                _btn(strings["allow_once"], "approve_once", "primary"),
                                _btn(strings["allow_session"], "approve_session"),
                                _btn(strings["allow_always"], "approve_always"),
                                _btn(strings["deny"], "deny", "danger"),
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
            except Exception as exc:
                logger.warning("[Feishu] localized send_exec_approval failed: %s", exc)
                return await original_send_exec(
                    self,
                    chat_id=chat_id,
                    command=command,
                    session_key=session_key,
                    description=description,
                    metadata=metadata,
                )

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
                "elements": [
                    {
                        "tag": "markdown",
                        "content": f"{icon} **{localized_label}** · {strings['by_user']}：{user_name}",
                    },
                ],
            }
            try:
                payload = json.dumps(card, ensure_ascii=False)
                body = self._build_update_message_body(msg_type="interactive", content=payload)
                request = self._build_update_message_request(message_id=message_id, request_body=body)
                await asyncio.to_thread(self._client.im.v1.message.update, request)
            except Exception as exc:
                logger.warning("[Feishu] Failed to update localized approval card %s: %s", message_id, exc)

        wrapped_update_card.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter._update_approval_card = wrapped_update_card

    original_handle_action = FeishuAdapter._handle_card_action_event
    if not getattr(original_handle_action, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_handle_action(self: Any, data: Any) -> None:
            event = getattr(data, "event", None)
            action = getattr(event, "action", None)
            action_value = getattr(action, "value", {}) or {}
            hermes_action = action_value.get("hermes_action") if isinstance(action_value, dict) else None
            if not hermes_action:
                return await original_handle_action(self, data)

            token = str(getattr(event, "token", "") or "")
            if token and self._is_card_action_duplicate(token):
                logger.debug("[Feishu] Dropping duplicate approval card action token: %s", token)
                return

            context = getattr(event, "context", None)
            chat_id = str(
                getattr(context, "open_chat_id", "")
                or getattr(context, "chat_id", "")
                or getattr(event, "open_chat_id", "")
                or ""
            )
            operator = getattr(event, "operator", None)
            open_id = str(getattr(operator, "open_id", "") or "")
            user_id = str(getattr(operator, "user_id", "") or "")
            union_id = str(getattr(operator, "union_id", "") or "")

            matched_key, state = _pop_approval_state(self, action_value.get("approval_id"), chat_id)
            if not state:
                logger.warning(
                    "[Feishu] Approval action received but state was not found: raw_id=%r chat_id=%s keys=%s",
                    action_value.get("approval_id"),
                    chat_id,
                    list(self._approval_state.keys())[:10],
                )
                return

            choice_map = {
                "approve_once": "once",
                "approve_session": "session",
                "approve_always": "always",
                "deny": "deny",
            }
            choice = choice_map.get(hermes_action, "deny")
            strings = approval_strings()
            label_map = {
                "once": strings["approved_once"],
                "session": strings["approved_session"],
                "always": strings["approved_always"],
                "deny": strings["denied"],
            }
            label = label_map.get(choice, strings["resolved"])

            sender_profile: dict[str, Any] = {}
            if open_id or user_id or union_id:
                try:
                    sender_profile = await self._resolve_sender_profile(
                        SimpleNamespace(
                            open_id=open_id or None,
                            user_id=user_id or None,
                            union_id=union_id or None,
                        )
                    )
                except Exception as exc:
                    logger.debug("[Feishu] Failed to resolve sender for approval card: %s", exc)
            user_name = (
                sender_profile.get("user_name")
                or open_id
                or user_id
                or union_id
                or strings["unknown_user"]
            )

            try:
                from tools.approval import resolve_gateway_approval

                count = resolve_gateway_approval(state["session_key"], choice)
                logger.info(
                    "[Feishu] Approval resolved: matched=%r session=%s choice=%s count=%d user=%s",
                    matched_key,
                    state["session_key"],
                    choice,
                    count,
                    user_name,
                )
            except Exception as exc:
                logger.error("Failed to resolve gateway approval from Feishu button: %s", exc)

            await self._update_approval_card(state.get("message_id", ""), label, user_name, choice)

        wrapped_handle_action.__hermes_feishu_plugin_wrapped__ = True
        FeishuAdapter._handle_card_action_event = wrapped_handle_action

    return True


def patch_disable_ack_reaction() -> bool:
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
    from gateway.platforms.feishu import FeishuAdapter

    original_guarded = FeishuAdapter._handle_message_with_guards
    original_send_typing = FeishuAdapter.send_typing
    original_stop_typing = FeishuAdapter.stop_typing

    if not getattr(original_send_typing, "__hermes_feishu_plugin_wrapped__", False):

        async def wrapped_send_typing(self: Any, chat_id: str, metadata=None) -> None:
            reply_targets, typing_reactions = _ensure_runtime_state(self)
            message_id = (
                get_reply_to_message_id()
                or str(reply_targets.get(chat_id, "") or "").strip()
            )
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
        chat_id = getattr(event.source, "chat_id", "") or "" if getattr(event, "source", None) else ""
        chat_lock = self._get_chat_lock(chat_id)
        message_id = getattr(event, "message_id", "") or ""
        reply_targets, _typing_reactions = _ensure_runtime_state(self)
        reply_token = set_reply_to_message_id(message_id)
        chat_type = getattr(getattr(event, "source", None), "chat_type", "dm")

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
    _PATCH_STATUS["plugin_name"] = plugin_name
    for key, patch_fn, detail in (
        (
            "feishu_ws_card_callbacks",
            patch_feishu_websocket_card_callbacks,
            "Patch Python lark_oapi websocket client so card.action.trigger frames are handled instead of being dropped",
        ),
        (
            "feishu_typing_reaction",
            patch_typing_reaction,
            "Use transient Typing reaction while processing inbound Feishu messages",
        ),
        (
            "feishu_disable_ack_reaction",
            patch_disable_ack_reaction,
            "Disable Hermes built-in persistent OK acknowledgement reaction",
        ),
        (
            "feishu_suppress_status_messages",
            patch_suppress_status_messages,
            "Suppress Feishu retry/fallback/context-pressure/tool-progress status messages so only the single reply card remains visible",
        ),
        (
            "feishu_exec_approval_localization",
            patch_exec_approval_localization,
            "Localize approval cards and make Feishu approval action handling more tolerant to callback payload differences",
        ),
        (
            "feishu_subagent_progress_relay",
            patch_subagent_progress_relay,
            "Relay delegated child tool activity into the parent progress channel so Feishu cards can show live subagent stages",
        ),
        (
            "feishu_streaming_cards",
            patch_streaming_cards,
            "Use a single reply-to interactive card for Feishu streaming updates and final answer delivery",
        ),
    ):
        try:
            ok = patch_fn()
            _PATCH_STATUS["patched"][key] = bool(ok)
            if ok:
                _PATCH_STATUS["details"][key] = detail
        except Exception as exc:
            _PATCH_STATUS["patched"][key] = False
            _PATCH_STATUS["details"][key] = f"deferred: {exc}"
            logger.debug("hermes_feishu_plugin deferred %s: %s", key, exc)
    return get_patch_status()


def get_patch_status() -> dict[str, Any]:
    return {
        "plugin_name": _PATCH_STATUS["plugin_name"],
        "plugin_dir": _PATCH_STATUS["plugin_dir"],
        "patched": dict(_PATCH_STATUS["patched"]),
        "details": dict(_PATCH_STATUS["details"]),
    }
