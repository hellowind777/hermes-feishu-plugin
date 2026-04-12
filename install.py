"""Local install shim for the Hermes Feishu plugin."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    """Expose ``src/`` to standalone installer execution."""
    src_dir = Path(__file__).resolve().parent / "src"
    src_text = str(src_dir)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)


_ensure_src_on_path()

from hermes_feishu_plugin.install import main  # noqa: E402


if __name__ == "__main__":
    main()
