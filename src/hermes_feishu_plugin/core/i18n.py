"""Locale helpers for Hermes Feishu plugin system messages."""

from __future__ import annotations

import locale
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

_SUPPORTED_LOCALES = {"zh_cn", "en_us"}
_DYNAMIC_SYSTEM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?P<prefix>💾\s*)?Skill '([^']+)' created\.", re.I),
        r"\g<prefix>已创建技能「\2」。",
    ),
    (
        re.compile(r"(?P<prefix>💾\s*)?Skill '([^']+)' updated\.", re.I),
        r"\g<prefix>已更新技能「\2」。",
    ),
    (
        re.compile(r"(?P<prefix>💾\s*)?Cron job '([^']+)' created\.", re.I),
        r"\g<prefix>已创建定时任务「\2」。",
    ),
    (
        re.compile(r"(?P<prefix>💾\s*)?Cron job '([^']+)' updated\.", re.I),
        r"\g<prefix>已更新定时任务「\2」。",
    ),
)


@lru_cache(maxsize=1)
def _detect_windows_locale() -> str | None:
    """Best-effort detect Windows UI locale when running inside WSL."""
    candidates = [
        shutil.which("powershell.exe"),
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/pwsh.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            result = subprocess.run(
                [
                    str(path),
                    "-NoProfile",
                    "-Command",
                    "[System.Globalization.CultureInfo]::InstalledUICulture.Name",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except Exception:
            continue
        value = str(result.stdout or "").strip().lower()
        if value:
            return value
    return None


def get_preferred_locale() -> str:
    """Return the preferred Feishu UI locale."""
    override = str(os.getenv("HERMES_FEISHU_LOCALE", "auto") or "auto").strip().lower()
    if override in _SUPPORTED_LOCALES:
        return override

    for candidate in (
        os.getenv("LC_ALL"),
        os.getenv("LC_MESSAGES"),
        os.getenv("LANG"),
        _detect_windows_locale(),
        locale.getlocale()[0],
    ):
        value = str(candidate or "").strip().lower()
        if value.startswith("zh"):
            return "zh_cn"
    return "en_us"


def prefers_chinese() -> bool:
    """Return True when the current locale should render Simplified Chinese."""
    return get_preferred_locale() == "zh_cn"


def select_text(zh_cn: str, en_us: str) -> str:
    """Return the display text for the current locale."""
    return zh_cn if prefers_chinese() else en_us


def with_i18n(content_key: str, zh_cn: str, en_us: str, **extra: Any) -> dict[str, Any]:
    """Build a locale-aware Feishu text payload with fallback content."""
    payload: dict[str, Any] = {
        content_key: select_text(zh_cn, en_us),
        "i18n_content": {
            "zh_cn": zh_cn,
            "en_us": en_us,
        },
    }
    payload.update(extra)
    return payload


def approval_strings() -> dict[str, str]:
    """Return localized approval-card strings."""
    if not prefers_chinese():
        return {
            "title": "⚠️ Command Approval Required",
            "reason_label": "Reason",
            "allow_once": "✅ Allow Once",
            "allow_session": "✅ Session",
            "allow_always": "✅ Always",
            "deny": "❌ Deny",
            "approved_once": "Approved once",
            "approved_session": "Approved for session",
            "approved_always": "Approved permanently",
            "denied": "Denied",
            "resolved": "Resolved",
            "by_user": "by",
            "unknown_user": "Unknown user",
            "fallback_hint": "If the buttons do not respond, send /approve, /approve session, /approve always, or /deny.",
        }
    return {
        "title": "⚠️ 命令审批请求",
        "reason_label": "原因",
        "allow_once": "✅ 仅本次允许",
        "allow_session": "✅ 本会话允许",
        "allow_always": "✅ 始终允许",
        "deny": "❌ 拒绝",
        "approved_once": "已批准一次",
        "approved_session": "本会话已批准",
        "approved_always": "已永久批准",
        "denied": "已拒绝",
        "resolved": "已处理",
        "by_user": "操作人",
        "unknown_user": "未知用户",
        "fallback_hint": "如果按钮点击后没有反应，请发送 /approve、/approve session、/approve always 或 /deny。",
    }


def translate_approval_label(label: str) -> str:
    """Translate known approval result labels."""
    mapping = {
        "Approved once": approval_strings()["approved_once"],
        "Approved for session": approval_strings()["approved_session"],
        "Approved permanently": approval_strings()["approved_always"],
        "Denied": approval_strings()["denied"],
        "Resolved": approval_strings()["resolved"],
    }
    return mapping.get(str(label or "").strip(), str(label or "").strip())


def localize_system_text(text: str) -> str:
    """Translate fixed Hermes system phrases without touching user/model text."""
    content = str(text or "")
    if not content or not prefers_chinese():
        return content

    replacements = {
        "Cronjob Response:": "定时任务响应：",
        "Gateway shutting down — Your current task will be interrupted.": "网关正在关闭——当前任务将被中断。",
        "Interrupting current task": "正在中断当前任务",
        "I'll respond to your message shortly.": "我会随后回复你的新消息。",
        "Note: The agent cannot see this message, and therefore cannot respond to it.": "注意：当前代理看不到这条消息，因此无法直接回应。",
        "Rate limited — switching to fallback provider...": "主 API 渠道触发限速，正在切换备用 API 渠道...",
        "Primary model failed — switching to fallback:": "主模型失败，正在切换备用 API 渠道：",
        "Empty/malformed response — switching to fallback...": "模型响应为空或格式异常，正在切换备用 API 渠道...",
        "Non-retryable error": "不可重试错误",
        "trying fallback": "正在尝试备用 API 渠道",
        "Max retries": "最大重试次数",
        "exhausted": "已耗尽",
        "Command Approval Required": "命令审批请求",
        "Reason:": "原因：",
        "script execution via -e/-c flag": "通过 -e/-c 参数执行脚本",
        "dangerous command": "危险命令",
        "Approved once": "已批准一次",
        "Approved for session": "本会话已批准",
        "Approved permanently": "已永久批准",
        "Denied": "已拒绝",
        "Resolved": "已处理",
        "Unknown user": "未知用户",
    }
    localized = content
    for source, target in replacements.items():
        localized = localized.replace(source, target)
    for pattern, replacement in _DYNAMIC_SYSTEM_PATTERNS:
        localized = pattern.sub(replacement, localized)
    localized = re.sub(
        r'To stop or manage this job, send me a new message \(e\.g\. "stop reminder ([^"]+)"\)\.',
        r'如需停止或管理此任务，请给我发一条新消息（例如“stop reminder \1”）。',
        localized,
    )
    return localized
