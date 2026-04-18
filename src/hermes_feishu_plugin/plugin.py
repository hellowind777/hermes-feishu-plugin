"""Hermes Feishu plugin entrypoint."""

from __future__ import annotations

import logging

from .channel.patches import apply_runtime_patches
from .core.sibling_bootstrap import sync_optional_plugins
from .install import sync_profile_plugin_links
from .tools.hooks import on_post_tool_call, on_pre_tool_call

logger = logging.getLogger(__name__)


def _ensure_plugin_active(**kwargs) -> None:
    """Ensure runtime patches are active before tool or LLM work begins."""
    del kwargs
    apply_runtime_patches()


def register(ctx) -> None:
    """Register hooks for the Hermes Feishu plugin."""
    try:
        apply_runtime_patches(plugin_name=ctx.manifest.name)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin deferred initial apply: %s", exc)

    try:
        ctx.register_hook("pre_llm_call", _ensure_plugin_active)
        ctx.register_hook("pre_tool_call", _ensure_plugin_active)
        ctx.register_hook("pre_tool_call", on_pre_tool_call)
        ctx.register_hook("post_tool_call", on_post_tool_call)
    except Exception as exc:
        logger.debug("hermes_feishu_plugin hook registration unavailable: %s", exc)

    try:
        synced = sync_profile_plugin_links(plugin_name=ctx.manifest.name)
        if synced:
            logger.info("hermes_feishu_plugin synced to profiles: %s", ", ".join(synced))
    except Exception as exc:
        logger.debug("hermes_feishu_plugin profile sync skipped: %s", exc)

    try:
        synced_optional = sync_optional_plugins()
        if synced_optional:
            logger.info("hermes_feishu_plugin bootstrapped sibling plugins: %s", ", ".join(synced_optional))
    except Exception as exc:
        logger.debug("hermes_feishu_plugin sibling bootstrap skipped: %s", exc)
