"""Directory-plugin shim for Hermes.

This root module keeps Hermes's recommended ``plugin.yaml`` + ``__init__.py``
directory layout while delegating the real implementation to ``src/`` so the
plugin can also be packaged via ``hermes_agent.plugins`` entry points.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    """Expose ``src/`` to Hermes's directory-plugin loader."""
    src_dir = Path(__file__).resolve().parent / "src"
    src_text = str(src_dir)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


def _ensure_package_search_path() -> None:
    """Allow early ``hermes_feishu_plugin.*`` imports through this shim."""
    package_dir = Path(__file__).resolve().parent / "src" / "hermes_feishu_plugin"
    if package_dir.exists():
        globals()["__path__"] = [str(package_dir)]


_ensure_src_on_path()
_ensure_package_search_path()

from hermes_feishu_plugin.plugin import register  # noqa: E402

__all__ = ["register"]
