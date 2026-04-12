"""Tests for plugin entrypoints and directory-plugin shims."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import hermes_feishu_plugin.plugin as plugin_module


class _FakeManifest:
    """Minimal manifest object used by register() tests."""

    name = "demo_feishu_plugin"


class _FakeContext:
    """Minimal plugin context used by register() tests."""

    def __init__(self) -> None:
        self.manifest = _FakeManifest()
        self.hooks: list[tuple[str, object]] = []

    def register_hook(self, hook_name: str, callback: object) -> None:
        """Record registered hooks for later assertions."""
        self.hooks.append((hook_name, callback))


def test_register_wires_runtime_patches_hooks_and_profile_sync(monkeypatch) -> None:
    """register() should apply patches, register hooks, and sync profile links."""
    apply_calls: list[str] = []
    sync_calls: list[str] = []

    def fake_apply_runtime_patches(*, plugin_name: str = "hermes_feishu_plugin") -> dict[str, object]:
        apply_calls.append(plugin_name)
        return {}

    def fake_sync_profile_plugin_links(*, plugin_name: str = "hermes_feishu_plugin") -> list[str]:
        sync_calls.append(plugin_name)
        return ["root", "default"]

    monkeypatch.setattr(plugin_module, "apply_runtime_patches", fake_apply_runtime_patches)
    monkeypatch.setattr(plugin_module, "sync_profile_plugin_links", fake_sync_profile_plugin_links)

    context = _FakeContext()
    plugin_module.register(context)

    assert apply_calls == ["demo_feishu_plugin"]
    assert sync_calls == ["demo_feishu_plugin"]
    assert [hook_name for hook_name, _ in context.hooks] == [
        "pre_llm_call",
        "pre_tool_call",
        "pre_tool_call",
        "post_tool_call",
    ]

    context.hooks[0][1]()
    context.hooks[1][1]()
    assert apply_calls == [
        "demo_feishu_plugin",
        "hermes_feishu_plugin",
        "hermes_feishu_plugin",
    ]


def test_root_directory_plugin_shim_exports_register() -> None:
    """The repository-root shim should expose a callable register symbol."""
    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("repo_root_plugin", repo_root / "__init__.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.register)
