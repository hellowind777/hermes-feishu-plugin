"""Best-effort bootstrap for sibling Hermes plugins stored in the shared dev folder."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
TARGET_PLUGIN_DIRS = ("hermes-market-intel-plugin",)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _iter_candidate_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.getenv("HERMES_MARKET_INTEL_PLUGIN_ROOT", "").strip()
    if configured:
        roots.append(Path(configured).expanduser())

    for name in TARGET_PLUGIN_DIRS:
        roots.append(_repo_root().parent / name)
    return roots


def _import_from_repo(repo_root: Path, module_name: str):
    src_dir = repo_root / "src"
    for path in (repo_root, src_dir):
        path_text = str(path)
        if path.exists() and path_text not in sys.path:
            sys.path.insert(0, path_text)
    return importlib.import_module(module_name)


def sync_optional_plugins() -> list[str]:
    """Discover and sync sibling plugins without coupling to their runtime logic."""
    synced_plugins: list[str] = []
    seen: set[Path] = set()

    for candidate in _iter_candidate_roots():
        root = candidate.expanduser()
        if root in seen or not (root / "plugin.yaml").exists():
            continue
        seen.add(root)
        try:
            install_module = _import_from_repo(root, "hermes_market_intel_plugin.install")
            layout_module = _import_from_repo(root, "hermes_market_intel_plugin.core.layout")
            install_module.sync_profile_plugin_links()
            layout_module.ensure_market_intel_layout()
            synced_plugins.append(root.name)
        except Exception as exc:
            logger.debug("Optional plugin bootstrap skipped for %s: %s", root, exc)

    return synced_plugins
