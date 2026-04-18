"""Install helpers for the Hermes Feishu plugin."""

from __future__ import annotations

from pathlib import Path
import shutil
import site

PLUGIN_LINK_NAME = "hermes_feishu_plugin"
LEGACY_LINK_NAMES = ("hermes-feishu-plugin",)
LEGACY_PLUGIN_DIR_NAMES = ("runtime_patches",)
STARTUP_PTH_NAME = "hermes_feishu_plugin_startup.pth"
SITECUSTOMIZE_NAME = "sitecustomize.py"
STARTUP_IMPORT_LINE = "import hermes_feishu_plugin.startup\n"
INSTALL_IGNORE_PATTERNS = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    "dist",
    "build",
    "*.egg-info",
    "docs",
)


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
        if not legacy_path.exists():
            continue
        if legacy_path.is_symlink():
            try:
                if legacy_path.resolve() == plugin_dir:
                    legacy_path.unlink()
                    continue
            except OSError:
                legacy_path.unlink()
                continue
        if legacy_path.is_dir():
            shutil.rmtree(legacy_path)
            continue
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


def _iter_site_package_dirs() -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen or not path.exists():
            return
        seen.add(resolved)
        paths.append(path)

    for raw_path in site.getsitepackages():
        path = Path(raw_path)
        add(path)

    hermes_venv_lib = Path.home() / ".hermes" / "hermes-agent" / "venv" / "lib"
    if hermes_venv_lib.exists():
        for path in sorted(hermes_venv_lib.glob("python*/site-packages")):
            add(path)

    return paths


def _write_startup_loader(plugins_root: Path) -> list[str]:
    synced: list[str] = []
    sitecustomize_path = plugins_root / SITECUSTOMIZE_NAME
    sitecustomize_path.write_text(STARTUP_IMPORT_LINE, encoding="utf-8")
    synced.append(str(sitecustomize_path))

    for site_dir in _iter_site_package_dirs():
        pth_path = site_dir / STARTUP_PTH_NAME
        pth_path.write_text(STARTUP_IMPORT_LINE, encoding="utf-8")
        synced.append(str(pth_path))
    return synced


def _copy_plugin_dir(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(*INSTALL_IGNORE_PATTERNS),
    )


def _create_plugin_link(plugins_dir: Path, plugin_dir: Path, plugin_name: str) -> Path:
    link_path = plugins_dir / plugin_name
    try:
        link_path.symlink_to(plugin_dir, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        _copy_plugin_dir(plugin_dir, link_path)
    return link_path


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
            if link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()

        _create_plugin_link(plugins_dir, plugin_dir, plugin_name)
        synced.append(scope)

    _write_startup_loader(root / "plugins")
    return synced


def main() -> None:
    """Link the plugin into all Hermes profile plugin directories."""
    for scope in sync_profile_plugin_links():
        print(scope)
