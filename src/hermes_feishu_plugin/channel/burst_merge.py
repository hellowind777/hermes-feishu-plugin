"""Feishu burst-message merge patches."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PENDING_EVENT_MERGE_WINDOW_SECONDS = 8.0


def patch_feishu_burst_merge() -> bool:
    """Merge near-simultaneous Feishu text/media bursts into one Hermes turn."""
    from gateway.platforms import base as platform_base
    from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType
    from gateway.platforms.feishu import FeishuAdapter

    mergeable_message_types = {
        MessageType.TEXT,
        MessageType.PHOTO,
        MessageType.VIDEO,
        MessageType.DOCUMENT,
        MessageType.AUDIO,
    }

    def pending_events_are_compatible(existing: MessageEvent, incoming: MessageEvent) -> bool:
        if existing.is_command() or incoming.is_command():
            return False
        if existing.message_type not in mergeable_message_types:
            return False
        if incoming.message_type not in mergeable_message_types:
            return False
        if existing.reply_to_message_id != incoming.reply_to_message_id:
            return False
        if existing.reply_to_text != incoming.reply_to_text:
            return False
        if getattr(existing.source, "thread_id", None) != getattr(incoming.source, "thread_id", None):
            return False
        if (existing.channel_prompt or incoming.channel_prompt) and existing.channel_prompt != incoming.channel_prompt:
            return False
        try:
            delta = abs((incoming.timestamp - existing.timestamp).total_seconds())
        except Exception:
            return False
        return delta <= _PENDING_EVENT_MERGE_WINDOW_SECONDS

    def merge_message_payload(existing: MessageEvent, incoming: MessageEvent) -> None:
        if incoming.text:
            existing.text = BasePlatformAdapter._merge_caption(existing.text, incoming.text)
        if incoming.media_urls:
            existing.media_urls.extend(incoming.media_urls)
        if incoming.media_types:
            existing.media_types.extend(incoming.media_types)
        if existing.message_type == MessageType.TEXT and incoming.message_type != MessageType.TEXT:
            existing.message_type = incoming.message_type
        if incoming.message_id:
            existing.message_id = incoming.message_id
        if incoming.raw_message is not None:
            existing.raw_message = incoming.raw_message
        if incoming.auto_skill:
            existing.auto_skill = incoming.auto_skill
        if incoming.channel_prompt:
            existing.channel_prompt = incoming.channel_prompt
        existing.timestamp = incoming.timestamp

    def merge_pending_message_event(
        pending_messages: dict[str, MessageEvent],
        session_key: str,
        event: MessageEvent,
    ) -> str:
        existing = pending_messages.get(session_key)
        if existing and pending_events_are_compatible(existing, event):
            merge_message_payload(existing, event)
            return "merged"
        pending_messages[session_key] = event
        return "replaced" if existing else "stored"

    def cross_batch_is_compatible(existing: MessageEvent, incoming: MessageEvent) -> bool:
        return (
            existing.reply_to_message_id == incoming.reply_to_message_id
            and existing.reply_to_text == incoming.reply_to_text
            and existing.source.thread_id == incoming.source.thread_id
        )

    def cancel_batch_task(task_map: dict[str, asyncio.Task], key: str) -> None:
        task = task_map.pop(key, None)
        if task and not task.done():
            task.cancel()

    def merge_batched_event(self: Any, primary: MessageEvent, secondary: MessageEvent) -> None:
        if secondary.text:
            primary.text = self._merge_caption(primary.text, secondary.text)
        if secondary.media_urls:
            primary.media_urls.extend(secondary.media_urls)
        if secondary.media_types:
            primary.media_types.extend(secondary.media_types)
        if primary.message_type == MessageType.TEXT and secondary.message_type != MessageType.TEXT:
            primary.message_type = secondary.message_type
        primary.timestamp = secondary.timestamp
        if secondary.message_id:
            primary.message_id = secondary.message_id
        if secondary.raw_message is not None:
            primary.raw_message = secondary.raw_message

    def matching_media_batch_keys(self: Any, text_key: str, event: MessageEvent) -> list[str]:
        prefix = f"{text_key}:media:"
        matches: list[str] = []
        for candidate_key, candidate in list(self._pending_media_batches.items()):
            if not candidate_key.startswith(prefix):
                continue
            if not self._cross_batch_is_compatible(candidate, event):
                continue
            matches.append(candidate_key)
        return matches

    def merge_pending_media_batches_into_text(self: Any, key: str, event: MessageEvent) -> int:
        merged = 0
        for media_key in self._matching_media_batch_keys(key, event):
            candidate = self._pending_media_batches.pop(media_key, None)
            if not candidate:
                continue
            self._cancel_batch_task(self._pending_media_batch_tasks, media_key)
            merged += len(candidate.media_urls)
            self._merge_batched_event(event, candidate)
        return merged

    def merge_pending_text_batch_into_media(self: Any, event: MessageEvent) -> bool:
        text_key = self._text_batch_key(event)
        candidate = self._pending_text_batches.get(text_key)
        if not candidate or not self._cross_batch_is_compatible(candidate, event):
            return False
        self._pending_text_batches.pop(text_key, None)
        self._pending_text_batch_counts.pop(text_key, None)
        self._cancel_batch_task(self._pending_text_batch_tasks, text_key)
        self._merge_batched_event(event, candidate)
        return True

    async def flush_media_batch_now(self: Any, key: str) -> None:
        event = self._pending_media_batches.pop(key, None)
        if not event:
            return
        merged_text = self._merge_pending_text_batch_into_media(event)
        logger.info(
            "[Feishu] Flushing media batch %s with %d attachment(s)%s",
            key,
            len(event.media_urls),
            " + text" if merged_text else "",
        )
        await self._handle_message_with_guards(event)

    async def flush_media_batch(self: Any, key: str) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(max(self._media_batch_delay_seconds, _PENDING_EVENT_MERGE_WINDOW_SECONDS))
            await self._flush_media_batch_now(key)
        finally:
            if self._pending_media_batch_tasks.get(key) is current_task:
                self._pending_media_batch_tasks.pop(key, None)

    async def flush_text_batch(self: Any, key: str) -> None:
        current_task = asyncio.current_task()
        try:
            pending = self._pending_text_batches.get(key)
            last_len = getattr(pending, "_last_chunk_len", 0) if pending else 0
            if last_len >= self._SPLIT_THRESHOLD:
                delay = self._text_batch_split_delay_seconds
            else:
                delay = self._text_batch_delay_seconds
            delay = max(
                delay,
                self._media_batch_delay_seconds,
                _PENDING_EVENT_MERGE_WINDOW_SECONDS,
            )
            await asyncio.sleep(delay)
            await self._flush_text_batch_now(key)
        finally:
            if self._pending_text_batch_tasks.get(key) is current_task:
                self._pending_text_batch_tasks.pop(key, None)

    async def flush_text_batch_now(self: Any, key: str) -> None:
        event = self._pending_text_batches.pop(key, None)
        self._pending_text_batch_counts.pop(key, None)
        if not event:
            return
        merged_attachments = self._merge_pending_media_batches_into_text(key, event)
        logger.info(
            "[Feishu] Flushing text batch %s (%d chars, %d attachment(s))",
            key,
            len(event.text or ""),
            len(event.media_urls) if merged_attachments else 0,
        )
        await self._handle_message_with_guards(event)

    platform_base.merge_pending_message_event = merge_pending_message_event
    FeishuAdapter._cross_batch_is_compatible = staticmethod(cross_batch_is_compatible)
    FeishuAdapter._cancel_batch_task = staticmethod(cancel_batch_task)
    FeishuAdapter._merge_batched_event = merge_batched_event
    FeishuAdapter._matching_media_batch_keys = matching_media_batch_keys
    FeishuAdapter._merge_pending_media_batches_into_text = merge_pending_media_batches_into_text
    FeishuAdapter._merge_pending_text_batch_into_media = merge_pending_text_batch_into_media
    FeishuAdapter._flush_media_batch = flush_media_batch
    FeishuAdapter._flush_media_batch_now = flush_media_batch_now
    FeishuAdapter._flush_text_batch = flush_text_batch
    FeishuAdapter._flush_text_batch_now = flush_text_batch_now
    return True
