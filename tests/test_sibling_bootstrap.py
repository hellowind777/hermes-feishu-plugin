"""Tests for optional sibling-plugin bootstrap."""

from __future__ import annotations

from pathlib import Path
import types

from hermes_feishu_plugin.core import sibling_bootstrap


def test_sync_optional_plugins_installs_market_intel_when_present(tmp_path, monkeypatch) -> None:
    """Sibling bootstrap should sync the market-intel plugin when the repo exists."""
    plugin_root = tmp_path / "hermes-market-intel-plugin"
    plugin_root.mkdir()
    (plugin_root / "plugin.yaml").write_text("name: hermes_market_intel_plugin\n", encoding="utf-8")

    install_calls = 0
    layout_calls = 0

    def fake_import_from_repo(repo_root: Path, module_name: str):
        nonlocal install_calls, layout_calls
        assert repo_root == plugin_root
        if module_name.endswith(".install"):
            return types.SimpleNamespace(sync_profile_plugin_links=lambda: _bump("install"))
        return types.SimpleNamespace(ensure_market_intel_layout=lambda: _bump("layout"))

    def _bump(kind: str):
        nonlocal install_calls, layout_calls
        if kind == "install":
            install_calls += 1
            return ["stock"]
        layout_calls += 1
        return []

    monkeypatch.setattr(sibling_bootstrap, "_iter_candidate_roots", lambda: [plugin_root])
    monkeypatch.setattr(sibling_bootstrap, "_import_from_repo", fake_import_from_repo)

    synced = sibling_bootstrap.sync_optional_plugins()

    assert synced == ["hermes-market-intel-plugin"]
    assert install_calls == 1
    assert layout_calls == 1
