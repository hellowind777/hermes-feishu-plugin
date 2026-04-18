"""Runtime patch entrypoint for the Hermes Feishu plugin."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..card.streaming import patch_streaming_cards
from .approval import patch_exec_approval_localization
from .burst_merge import patch_feishu_burst_merge
from .status_patches import patch_suppress_status_messages
from .typing import patch_disable_ack_reaction, patch_typing_reaction
from .ws_callbacks import patch_feishu_websocket_card_callbacks

logger = logging.getLogger(__name__)

_PATCH_STATUS: dict[str, Any] = {
    "plugin_name": "hermes_feishu_plugin",
    "plugin_dir": str(Path(__file__).resolve().parents[3]),
    "patched": {},
    "details": {},
}


def apply_runtime_patches(*, plugin_name: str = "hermes_feishu_plugin") -> dict[str, Any]:
    """Apply all Feishu runtime patches idempotently."""
    _PATCH_STATUS["plugin_name"] = plugin_name
    patch_plan = (
        ("feishu_ws_card_callbacks", patch_feishu_websocket_card_callbacks, "Handle card.action.trigger WS frames instead of dropping them"),
        ("feishu_burst_merge", patch_feishu_burst_merge, "Merge near-simultaneous Feishu text/media bursts into one Hermes turn"),
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
