"""Early Hermes gateway patch loader.

Hermes directory plugins are normally discovered after a Feishu message has
already entered the gateway.  This tiny startup hook lets the same official
plugin package apply its Feishu runtime patches before the gateway adds ACK
reactions or emits lifecycle status messages.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


try:
    from .channel.patches import apply_runtime_patches
    from .core.sibling_bootstrap import sync_optional_plugins

    apply_runtime_patches(plugin_name="hermes_feishu_plugin_startup")
    sync_optional_plugins()
except Exception as exc:
    logger.debug("hermes_feishu_plugin startup loader skipped: %s", exc)
