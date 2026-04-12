"""Hermes Feishu plugin entrypoint."""

from __future__ import annotations

import logging

from .install import sync_profile_plugin_links
from .patches import apply_runtime_patches

logger = logging.getLogger(__name__)


def _ensure_plugin_active(**kwargs) -> None:
    apply_runtime_patches()


def register(ctx) -> None:
    try:
        apply_runtime_patches(plugin_name=ctx.manifest.name)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin deferred initial apply: %s", exc)

    try:
        ctx.register_hook("pre_llm_call", _ensure_plugin_active)
        ctx.register_hook("pre_tool_call", _ensure_plugin_active)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin hook registration unavailable: %s", exc)

    try:
        synced = sync_profile_plugin_links(plugin_name=ctx.manifest.name)
        if synced:
            logger.info("hermes_feishu_plugin synced to profiles: %s", ", ".join(synced))
    except Exception as exc:
        logger.debug("hermes_feishu_plugin profile sync skipped: %s", exc)
