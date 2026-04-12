"""Install helpers for the Hermes Feishu plugin."""

from __future__ import annotations

from pathlib import Path
import shutil

PLUGIN_LINK_NAME = "hermes_feishu_plugin"
LEGACY_LINK_NAMES = ("hermes-feishu-plugin",)
LEGACY_PLUGIN_DIR_NAMES = ("runtime_patches",)


def _resolve_plugin_root() -> Path:
    """Return the repository root for directory-plugin symlink installs."""
    return Path(__file__).resolve().parents[2]


def _iter_plugin_dirs(root: Path) -> list[tuple[str, Path]]:
    plugin_dirs: list[tuple[str, Path]] = [("root", root / "plugins")]
    profiles_root = root / "profiles"
    if not profiles_root.exists():
        return plugin_dirs

    for profile_dir in sorted(path for path in profiles_root.iterdir() if path.is_dir()):
        plugin_dirs.append((profile_dir.name, profile_dir / "plugins"))
    return plugin_dirs


def _remove_legacy_links(plugins_dir: Path, plugin_dir: Path, plugin_name: str) -> None:
    for legacy_name in LEGACY_LINK_NAMES:
        if legacy_name == plugin_name:
            continue
        legacy_path = plugins_dir / legacy_name
        if legacy_path.is_symlink() and legacy_path.resolve() == plugin_dir:
            legacy_path.unlink()


def _remove_legacy_plugin_dirs(plugins_dir: Path) -> None:
    """Remove superseded local plugin directories from the plugin root."""
    for legacy_name in LEGACY_PLUGIN_DIR_NAMES:
        legacy_path = plugins_dir / legacy_name
        if legacy_path.is_symlink():
            legacy_path.unlink()
            continue
        if legacy_path.is_dir():
            shutil.rmtree(legacy_path)


def sync_profile_plugin_links(*, plugin_name: str = PLUGIN_LINK_NAME) -> list[str]:
    """Ensure the plugin is linked into root and profile plugin directories."""
    plugin_dir = _resolve_plugin_root()
    root = Path.home() / ".hermes"
    synced: list[str] = []

    for scope, plugins_dir in _iter_plugin_dirs(root):
        plugins_dir.mkdir(parents=True, exist_ok=True)
        _remove_legacy_links(plugins_dir, plugin_dir, plugin_name)
        _remove_legacy_plugin_dirs(plugins_dir)

        link_path = plugins_dir / plugin_name
        if link_path.is_symlink():
            if link_path.resolve() == plugin_dir:
                synced.append(scope)
                continue
            link_path.unlink()

        if link_path.exists():
            continue

        link_path.symlink_to(plugin_dir, target_is_directory=True)
        synced.append(scope)

    return synced


def main() -> None:
    """Link the plugin into all Hermes profile plugin directories."""
    for scope in sync_profile_plugin_links():
        print(scope)
