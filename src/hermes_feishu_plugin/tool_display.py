"""Structured tool-use display helpers aligned with OpenClaw's card UX."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .models import ToolDisplayBlock, ToolDisplayStep
from .runtime_state import get_chat_state

_DEFAULT_SUMMARY_PREFERENCE = ("matched", "code", "quoted", "url", "line")
_MAX_BLOCK_CHARS = 1400

_TOOL_DESCRIPTORS = (
    {
        "aliases": ("skill",),
        "icon_token": "app-default_outlined",
        "title": "Load skill",
        "param_keys": ("skill", "name"),
        "kind": "skill",
        "patterns": (re.compile(r"^(?:load|use)\s+skill\s+(.+)$", re.I),),
    },
    {
        "aliases": ("read", "open"),
        "icon_token": "file-link-text_outlined",
        "title": "Read",
        "param_keys": ("file_path", "path", "file"),
        "kind": "path",
        "patterns": (re.compile(r"^(?:read|open)\s+(?:file\s+)?(.+)$", re.I),),
    },
    {
        "aliases": ("write", "edit"),
        "icon_token": "edit_outlined",
        "title": "Edit",
        "param_keys": ("file_path", "path", "file"),
        "kind": "path",
        "patterns": (re.compile(r"^(?:edit|write)\s+(?:file\s+)?(.+)$", re.I),),
    },
    {
        "aliases": ("web_search", "web-search", "search"),
        "icon_token": "search_outlined",
        "title": "Search web",
        "param_keys": ("query", "q"),
        "kind": "search",
        "patterns": (re.compile(r"^(?:search\s+(?:web\s+)?(?:for|about)|query)\s+(.+)$", re.I),),
    },
    {
        "aliases": ("web_fetch", "web-fetch", "fetch"),
        "icon_token": "language_outlined",
        "title": "Fetch web page",
        "param_keys": ("url",),
        "kind": "url",
        "patterns": (re.compile(r"^(?:fetch|open)\s+(?:web\s+page\s+)?(?:from\s+)?(.+)$", re.I),),
    },
    {
        "aliases": ("grep",),
        "icon_token": "doc-search_outlined",
        "title": "Search text",
        "param_keys": ("pattern", "glob", "path", "file_path"),
        "kind": "generic",
        "patterns": (re.compile(r"^(?:search\s+text(?:\s+by\s+pattern)?|grep)\s+(.+)$", re.I),),
    },
    {
        "aliases": ("glob",),
        "icon_token": "folder_outlined",
        "title": "Search files",
        "param_keys": ("pattern",),
        "kind": "generic",
    },
    {
        "aliases": ("exec", "bash", "command", "run"),
        "icon_token": "setting_outlined",
        "title": "Run command",
        "param_keys": ("description", "command", "script"),
        "kind": "command",
        "patterns": (re.compile(r"^(?:run|execute)\s+(?:command|script)?\s*(.+)$", re.I),),
    },
    {
        "aliases": ("browser", "playwright", "navigate"),
        "icon_token": "browser-mac_outlined",
        "title": "Browser",
        "param_keys": ("url",),
        "kind": "url",
    },
    {
        "aliases": ("agent", "task", "spawn", "delegate"),
        "icon_token": "robot_outlined",
        "title": "Run sub-agent",
        "param_keys": ("task", "description", "prompt"),
        "kind": "generic",
    },
)


def record_tool_start(
    adapter: Any,
    chat_id: str,
    *,
    tool_name: str,
    args: dict[str, Any] | None,
    task_id: str,
) -> None:
    """Append a running tool step for the current chat."""
    state = get_chat_state(adapter, chat_id)
    descriptor = _resolve_descriptor(tool_name)
    detail = _extract_detail(args or {}, descriptor)
    step = ToolDisplayStep(
        title=descriptor["title"] if descriptor else _humanize_tool_name(tool_name),
        detail=detail,
        icon_token=descriptor["icon_token"] if descriptor else "setting-inter_outlined",
        status="running",
        started_at=time.monotonic(),
    )
    state.tool_steps.append(step)
    state.fallback_tool_lines.clear()
    key = _tool_key(tool_name, task_id)
    state.tool_call_indices.setdefault(key, []).append(len(state.tool_steps) - 1)
    if state.tool_started_at <= 0:
        state.tool_started_at = time.monotonic()


def record_tool_finish(
    adapter: Any,
    chat_id: str,
    *,
    tool_name: str,
    args: dict[str, Any] | None,
    result: str,
    task_id: str,
) -> None:
    """Resolve the most recent matching running step and mark it complete."""
    state = get_chat_state(adapter, chat_id)
    key = _tool_key(tool_name, task_id)
    index = _pop_tool_index(state.tool_call_indices, key)
    if index is None:
        record_tool_start(adapter, chat_id, tool_name=tool_name, args=args, task_id=task_id)
        index = len(state.tool_steps) - 1

    step = state.tool_steps[index]
    duration_ms = int(max(0.0, time.monotonic() - step.started_at) * 1000) if step.started_at else None
    status, result_block, error_block = _parse_tool_result(result)
    step.status = status
    step.duration_ms = duration_ms
    step.result_block = result_block
    step.error_block = error_block
    state.tool_elapsed_ms = int(max(0.0, time.monotonic() - state.tool_started_at) * 1000) if state.tool_started_at else 0


def fallback_steps_from_lines(lines: list[str]) -> list[ToolDisplayStep]:
    """Convert plain fallback progress lines into structured running steps."""
    steps: list[ToolDisplayStep] = []
    for line in lines:
        cleaned = " ".join(str(line or "").split()).strip()
        if not cleaned:
            continue
        title = cleaned
        detail = None
        if " — " in cleaned:
            title, detail = cleaned.split(" — ", 1)
        steps.append(
            ToolDisplayStep(
                title=title.strip(),
                detail=detail.strip() if detail else None,
                icon_token="setting-inter_outlined",
                status="running",
            )
        )
    return steps


def _resolve_descriptor(tool_name: str | None) -> dict[str, Any] | None:
    normalized = _normalize_tool_name(tool_name or "")
    for descriptor in _TOOL_DESCRIPTORS:
        for alias in descriptor["aliases"]:
            if normalized == alias or normalized.startswith(f"{alias}_") or normalized.startswith(f"{alias}-"):
                return descriptor
    return None


def _tool_key(tool_name: str, task_id: str) -> str:
    return f"{task_id}:{_normalize_tool_name(tool_name)}"


def _pop_tool_index(mapping: dict[str, list[int]], key: str) -> int | None:
    indices = mapping.get(key)
    if not indices:
        return None
    index = indices.pop(0)
    if not indices:
        mapping.pop(key, None)
    return index


def _normalize_tool_name(tool_name: str) -> str:
    return str(tool_name or "").strip().lower().replace(" ", "_")


def _humanize_tool_name(tool_name: str) -> str:
    cleaned = _normalize_tool_name(tool_name).replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return "Tool"
    return cleaned[:1].upper() + cleaned[1:]


def _extract_detail(args: dict[str, Any], descriptor: dict[str, Any] | None) -> str | None:
    if not descriptor:
        return None

    for key in descriptor.get("param_keys", ()):
        value = args.get(key)
        text = _extract_scalar_text(value)
        if text:
            return _sanitize_detail(descriptor.get("kind", "generic"), text)
    return None


def _extract_scalar_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _sanitize_detail(kind: str, value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if not cleaned:
        return ""
    if kind == "skill":
        return cleaned.replace("_", " ").replace("-", " ")
    if kind == "path":
        parts = re.split(r"[\\/]+", cleaned.rstrip("/\\"))
        return parts[-1] if parts else cleaned
    if kind == "url":
        return cleaned.replace("from ", "", 1)
    if kind == "command":
        return _redact_inline_secrets(cleaned)
    return cleaned


def _parse_tool_result(result: str) -> tuple[str, ToolDisplayBlock | None, ToolDisplayBlock | None]:
    text = str(result or "").strip()
    if not text:
        return "success", None, None

    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        if parsed.get("error") or parsed.get("success") is False:
            content = _stringify_block(parsed.get("error") or parsed)
            return "error", None, ToolDisplayBlock(language="text", content=content)
        result_payload = parsed.get("result")
        if result_payload not in (None, "", []):
            return "success", _build_block(result_payload), None
        if parsed:
            return "success", _build_block(parsed), None

    if '"error"' in text.lower() or text.lower().startswith("error:"):
        return "error", None, ToolDisplayBlock(language="text", content=_truncate_block(text))
    return "success", _build_block(text), None


def _build_block(value: Any) -> ToolDisplayBlock | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except Exception:
            return ToolDisplayBlock(language="text", content=_truncate_block(stripped))
        return ToolDisplayBlock(language="json", content=_truncate_block(json.dumps(parsed, ensure_ascii=False, indent=2)))
    if isinstance(value, (dict, list)):
        return ToolDisplayBlock(language="json", content=_truncate_block(json.dumps(value, ensure_ascii=False, indent=2)))
    return ToolDisplayBlock(language="text", content=_truncate_block(str(value)))


def _stringify_block(value: Any) -> str:
    if isinstance(value, str):
        return _truncate_block(value.strip())
    try:
        return _truncate_block(json.dumps(value, ensure_ascii=False, indent=2))
    except Exception:
        return _truncate_block(str(value))


def _truncate_block(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").strip()
    if len(cleaned) <= _MAX_BLOCK_CHARS:
        return cleaned
    return f"{cleaned[:_MAX_BLOCK_CHARS].rstrip()}\n…"


def _redact_inline_secrets(text: str) -> str:
    return re.sub(
        r"(?i)(token|secret|password|key|bearer)(\s*[=:]\s*)([^\s]+)",
        r"\1\2[redacted]",
        text,
    )
