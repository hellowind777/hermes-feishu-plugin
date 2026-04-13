"""Idle heartbeat helpers for the single live Feishu card."""

from __future__ import annotations

import time
from typing import Any

from ..channel.runtime_state import (
    get_chat_state,
    get_heartbeat_status_text,
    get_last_visible_activity_at,
    set_heartbeat_status_text,
)
from ..core.i18n import select_text

HEARTBEAT_IDLE_SECONDS = 10 * 60
HEARTBEAT_BUCKET_MINUTES = 10


def refresh_heartbeat_status(adapter: Any, chat_id: str) -> bool:
    """Refresh the lightweight heartbeat status and report whether it changed."""
    state = get_chat_state(adapter, chat_id)
    now = time.monotonic()
    last_activity_at = get_last_visible_activity_at(adapter, chat_id) or state.started_at or now
    idle_seconds = max(0.0, now - last_activity_at)
    current_text = get_heartbeat_status_text(adapter, chat_id)

    if idle_seconds < HEARTBEAT_IDLE_SECONDS:
        if current_text:
            set_heartbeat_status_text(adapter, chat_id, "")
            return True
        return False

    idle_minutes = int(idle_seconds // 60)
    bucket_minutes = max(
        HEARTBEAT_BUCKET_MINUTES,
        (idle_minutes // HEARTBEAT_BUCKET_MINUTES) * HEARTBEAT_BUCKET_MINUTES,
    )
    next_text = select_text(
        f"仍在处理中 · 最近 {bucket_minutes} 分钟无新进展",
        f"Still working · no new progress for {bucket_minutes} min",
    )
    if next_text == current_text:
        return False
    set_heartbeat_status_text(adapter, chat_id, next_text)
    return True
