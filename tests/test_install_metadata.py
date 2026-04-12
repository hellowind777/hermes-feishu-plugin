"""Tests for install helpers and packaging metadata."""

from __future__ import annotations

from pathlib import Path
import tomllib

import hermes_feishu_plugin.install as install_module


def test_sync_profile_plugin_links_creates_root_and_profile_symlinks(tmp_path, monkeypatch) -> None:
    """Directory-plugin installs should link root and profile plugin folders."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    home_root = tmp_path / "home"
    hermes_root = home_root / ".hermes"
    root_plugins = hermes_root / "plugins"
    default_plugins = hermes_root / "profiles" / "default" / "plugins"
    root_plugins.mkdir(parents=True)
    default_plugins.mkdir(parents=True)

    legacy_link = root_plugins / "hermes-feishu-plugin"
    legacy_link.symlink_to(repo_root, target_is_directory=True)

    monkeypatch.setattr(install_module, "_resolve_plugin_root", lambda: repo_root)
    monkeypatch.setattr(install_module.Path, "home", lambda: home_root)

    synced_scopes = install_module.sync_profile_plugin_links()

    assert set(synced_scopes) == {"root", "default"}
    root_link = root_plugins / "hermes_feishu_plugin"
    default_link = default_plugins / "hermes_feishu_plugin"
    assert root_link.is_symlink()
    assert default_link.is_symlink()
    assert root_link.resolve() == repo_root
    assert default_link.resolve() == repo_root
    assert not legacy_link.exists()


def test_project_metadata_declares_directory_plugin_and_entrypoint_support() -> None:
    """Repository metadata should advertise Hermes-supported plugin loading modes."""
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    entrypoints = pyproject_data["project"]["entry-points"]["hermes_agent.plugins"]

    assert entrypoints["hermes_feishu_plugin"] == "hermes_feishu_plugin.plugin"
    assert "pytest>=8.0" in pyproject_data["project"]["optional-dependencies"]["test"]

    plugin_yaml = (repo_root / "plugin.yaml").read_text(encoding="utf-8")
    assert "provides_hooks:" in plugin_yaml
    for hook_name in ("pre_llm_call", "pre_tool_call", "post_tool_call"):
        assert f"  - {hook_name}" in plugin_yaml
