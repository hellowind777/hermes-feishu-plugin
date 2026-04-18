"""Status-message suppression patches."""

from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from ..card.streaming import _finalize_card as finalize_progress_card, sync_progress_card
from ..core.i18n import localize_system_text
from ..core.mode import should_stream
from .common import (
    extract_edit_content,
    extract_send_content,
    replace_edit_content,
    replace_send_content,
)
from .runtime_state import (
    get_generation,
    get_chat_state,
    remember_pending_status_text,
    remember_tool_steps,
)
from .state import get_chat_generation
from .status_filter import (
    is_interrupt_status_message,
    is_model_switch_status_message,
    parse_tool_progress_lines,
    should_suppress_status_message,
)


def _send_result(*, success: bool = True, message_id: str | None = None) -> Any:
    try:
        from gateway.platforms.base import SendResult

        return SendResult(success=success, message_id=message_id)
    except Exception:
        return SimpleNamespace(success=success, message_id=message_id)


def _current_generation_matches(adapter: Any, chat_id: str) -> bool:
    expected = get_chat_generation()
    if expected <= 0:
        return True
    return expected == get_generation(adapter, chat_id)


def _fallback_channel_label(index: int) -> str:
    try:
        from hermes_cli.config import load_config

        fallbacks = load_config().get("fallback_providers") or []
    except Exception:
        fallbacks = []

    if index <= 0 or index > len(fallbacks):
        return f"第 {index} 备用 API 渠道" if index > 0 else "备用 API 渠道"

    fallback = fallbacks[index - 1] or {}
    base_url = str(fallback.get("base_url") or "").lower()
    provider = str(fallback.get("provider") or "custom")
    model = str(fallback.get("model") or "").strip()
    api_mode = str(fallback.get("api_mode") or "").strip()

    if "codexzh.com" in base_url:
        name = "codexzh"
    elif "flux-code.cc" in base_url:
        name = "flux-code"
    elif "kimi" in base_url or "kimi" in provider.lower():
        name = "Kimi"
    else:
        name = provider

    details = "，".join(part for part in (model, api_mode) if part)
    return f"第 {index} 备用 API 渠道：{name}{f'（{details}）' if details else ''}"


def _model_switch_display_line(adapter: Any, chat_id: str, content: str) -> str:
    cleaned = localize_system_text(content)
    state = get_chat_state(adapter, chat_id)
    if "Primary model failed" in content or "Primary model failed" in cleaned:
        state.fallback_switch_count += 1
        return f"🔄 已切换到{_fallback_channel_label(state.fallback_switch_count)}"
    if "Rate limited" in content:
        return "⚠️ 主 API 渠道触发限速，正在切换备用 API 渠道"
    if "Empty/malformed response" in content:
        return "⚠️ 主 API 渠道响应异常，正在切换备用 API 渠道"
    if "Non-retryable error" in content:
        return "⚠️ 主 API 渠道请求失败，正在尝试备用 API 渠道"
    return cleaned


def _build_send_wrapper(original_send):
    async def wrapped_send(self: Any, *args, **kwargs):
        content = extract_send_content(args, kwargs)
        chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
        if chat_id and not _current_generation_matches(self, chat_id):
            return _send_result()
        handled = await maybe_handle_status_message(
            self,
            chat_id=chat_id,
            content=content,
            metadata=kwargs.get("metadata"),
        )
        if handled is not None:
            return handled
        localized = localize_system_text(content)
        finalized = await maybe_handle_final_response(
            self,
            chat_id=chat_id,
            content=localized,
        )
        if finalized is not None:
            return finalized
        args, kwargs = replace_send_content(args, kwargs, localized)
        return await original_send(self, *args, **kwargs)

    wrapped_send.__hermes_feishu_plugin_wrapped__ = True
    return wrapped_send


def _build_edit_wrapper(original_edit):
    async def wrapped_edit(self: Any, *args, **kwargs):
        content = extract_edit_content(args, kwargs)
        chat_id = str(kwargs.get("chat_id") or (args[0] if len(args) >= 1 else "") or "").strip()
        message_id = str(kwargs.get("message_id") or (args[1] if len(args) >= 2 else "") or "").strip()
        if chat_id and not _current_generation_matches(self, chat_id):
            return _send_result(message_id=message_id)
        handled = await maybe_handle_status_message(
            self,
            chat_id=chat_id,
            content=content,
            message_id=message_id,
        )
        if handled is not None:
            return handled
        localized = localize_system_text(content)
        args, kwargs = replace_edit_content(args, kwargs, localized)
        return await original_edit(self, *args, **kwargs)

    wrapped_edit.__hermes_feishu_plugin_wrapped__ = True
    return wrapped_edit


async def maybe_handle_status_message(
    adapter: Any,
    *,
    chat_id: str,
    content: str,
    metadata: Any = None,
    message_id: str | None = None,
) -> Any | None:
    """Consume Hermes internal progress text and route it into the live card."""
    if chat_id and not _current_generation_matches(adapter, chat_id):
        return _send_result(message_id=message_id)

    if chat_id and is_model_switch_status_message(content):
        remember_pending_status_text(adapter, chat_id, _model_switch_display_line(adapter, chat_id, content))
        if should_stream(adapter, chat_id):
            patched_id = await sync_progress_card(adapter, chat_id, metadata=metadata)
            return _send_result(message_id=patched_id or message_id)
        return _send_result(message_id=message_id)

    if chat_id and is_interrupt_status_message(content):
        return _send_result(message_id=message_id)

    tool_lines = parse_tool_progress_lines(content) if chat_id else []
    if tool_lines:
        remember_tool_steps(adapter, chat_id, tool_lines)
        if should_stream(adapter, chat_id):
            patched_id = await sync_progress_card(adapter, chat_id, metadata=metadata)
            return _send_result(message_id=patched_id or message_id)
        return _send_result(message_id=message_id)

    if should_suppress_status_message(content):
        return _send_result(message_id=message_id)
    return None


async def maybe_handle_final_response(
    adapter: Any,
    *,
    chat_id: str,
    content: str,
) -> Any | None:
    """Fold a non-streaming final reply back into the existing live card."""
    cleaned = str(content or "").strip()
    if not chat_id or not cleaned or should_suppress_status_message(cleaned):
        return None
    if not _current_generation_matches(adapter, chat_id):
        return _send_result()
    if parse_tool_progress_lines(cleaned):
        return None
    if not should_stream(adapter, chat_id):
        return None

    state = get_chat_state(adapter, chat_id)
    if not state.card_message_id or state.phase in {"completed", "aborted", "terminated"}:
        return None

    if await finalize_progress_card(adapter, chat_id, cleaned):
        return _send_result(message_id=state.card_message_id)
    return None


def patch_suppress_status_messages() -> bool:
    """Suppress internal progress text so Feishu keeps one live card."""
    from gateway.platforms.feishu import FeishuAdapter

    original_send = FeishuAdapter.send
    if not getattr(original_send, "__hermes_feishu_plugin_wrapped__", False):
        FeishuAdapter.send = _build_send_wrapper(original_send)

    original_edit = FeishuAdapter.edit_message
    if not getattr(original_edit, "__hermes_feishu_plugin_wrapped__", False):
        FeishuAdapter.edit_message = _build_edit_wrapper(original_edit)

    return True
