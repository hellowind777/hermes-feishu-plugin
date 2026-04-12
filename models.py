"""Shared data models for the Hermes Feishu plugin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ToolStatus = Literal["running", "success", "error"]


@dataclass(slots=True)
class ToolDisplayBlock:
    """Structured block rendered under a tool step."""

    language: Literal["json", "text"]
    content: str


@dataclass(slots=True)
class ToolDisplayStep:
    """Single tool-use step rendered in Feishu cards."""

    title: str
    detail: str | None = None
    icon_token: str = "setting_outlined"
    status: ToolStatus = "running"
    result_block: ToolDisplayBlock | None = None
    error_block: ToolDisplayBlock | None = None
    duration_ms: int | None = None
    started_at: float = 0.0
