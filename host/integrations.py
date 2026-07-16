"""Agent detection and idempotent lifecycle-hook integration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Iterable


CODEX_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
)

CLAUDE_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "SessionEnd",
)

GEMINI_EVENTS = (
    "SessionStart",
    "BeforeAgent",
    "BeforeTool",
    "AfterTool",
    "Notification",
    "PreCompress",
    "AfterAgent",
    "SessionEnd",
)


@dataclass(frozen=True)
class AgentAdapter:
    key: str
    display_name: str
    executable: str
    config_parts: tuple[str, ...]
    events: tuple[str, ...]
    timeout: int
    detection_parts: tuple[tuple[str, ...], ...]
    handler_name: bool = False

    def config_path(self, home: Path) -> Path:
        return home.joinpath(*self.config_parts)

    def detected(self, home: Path) -> bool:
        if shutil.which(self.executable):
            return True
        return any(home.joinpath(*parts).exists() for parts in self.detection_parts)


ADAPTERS = {
    "codex": AgentAdapter(
        key="codex",
        display_name="Codex",
        executable="codex",
        config_parts=(".codex", "hooks.json"),
        events=CODEX_EVENTS,
        timeout=5,
        detection_parts=(
            (".codex", "config.toml"),
            (".codex", "hooks.json"),
            (".codex", "auth.json"),
        ),
    ),
    "claude": AgentAdapter(
        key="claude",
        display_name="Claude Code",
        executable="claude",
        config_parts=(".claude", "settings.json"),
        events=CLAUDE_EVENTS,
        timeout=5,
        detection_parts=(
            (".claude", "settings.json"),
            (".claude", "projects"),
            (".claude", "sessions"),
        ),
    ),
    "gemini": AgentAdapter(
        key="gemini",
        display_name="Gemini CLI",
        executable="gemini",
        config_parts=(".gemini", "settings.json"),
        events=GEMINI_EVENTS,
        timeout=5000,
        detection_parts=((".gemini", "settings.json"),),
        handler_name=True,
    ),
}

MANAGED_COMMAND_MARKERS = (
    "dualkey-light",
    "dualkey_light.py",
)


@dataclass(frozen=True)
class IntegrationResult:
    key: str
    display_name: str
    path: Path
    changed: bool
    installed: bool
    backup: Path | None
    managed_entries: int


def runtime_hook_parts() -> list[str]:
    """Return a stable hook command for source and PyInstaller builds."""
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        if executable.stem.lower().endswith("-service"):
            suffix = executable.suffix
            executable = executable.with_name(f"dualkey-light{suffix}")
        return [str(executable), "hook"]
    script = Path(__file__).resolve().with_name("dualkey_light.py")
    return [str(executable), str(script), "hook"]


def format_command(parts: Iterable[str], platform: str | None = None) -> str:
    values = list(parts)
    platform = os.name if platform is None else platform
    return subprocess.list2cmdline(values) if platform == "nt" else shlex.join(values)


def runtime_hook_command() -> str:
    return format_command(runtime_hook_parts())


def agent_hook_command(command: str, agent_key: str) -> str:
    return f"{command} --agent {agent_key}"


def parse_agent_selection(selection: str, home: Path) -> list[AgentAdapter]:
    normalized = selection.strip().lower()
    if normalized == "auto":
        return [adapter for adapter in ADAPTERS.values() if adapter.detected(home)]
    if normalized == "all":
        return list(ADAPTERS.values())
    keys = [item.strip() for item in normalized.split(",") if item.strip()]
    unknown = sorted(set(keys) - set(ADAPTERS))
    if unknown:
        raise ValueError(f"unknown agent integration(s): {', '.join(unknown)}")
    return [ADAPTERS[key] for key in keys]


def detect_agents(home: Path | None = None) -> list[AgentAdapter]:
    home = Path.home() if home is None else home
    return [adapter for adapter in ADAPTERS.values() if adapter.detected(home)]


def is_managed_handler(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    command = str(value.get("command") or "").lower().replace("\\", "/")
    return "hook" in command and any(marker in command for marker in MANAGED_COMMAND_MARKERS)


def _handler(adapter: AgentAdapter, command: str) -> dict[str, Any]:
    handler: dict[str, Any] = {
        "type": "command",
        "command": command,
        "timeout": adapter.timeout,
    }
    if adapter.handler_name:
        handler["name"] = "dualkey-signal-light"
        handler["description"] = "Update the DualKey agent status light"
    elif adapter.key == "codex":
        handler["statusMessage"] = "Updating DualKey Signal Light"
    return handler


def _remove_managed_groups(hooks: dict[str, Any]) -> tuple[dict[str, Any], int]:
    cleaned: dict[str, Any] = {}
    removed = 0
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            cleaned[event] = groups
            continue
        event_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                event_groups.append(group)
                continue
            remaining = []
            for handler in group["hooks"]:
                if is_managed_handler(handler):
                    removed += 1
                else:
                    remaining.append(handler)
            if remaining:
                replacement = dict(group)
                replacement["hooks"] = remaining
                event_groups.append(replacement)
        if event_groups:
            cleaned[event] = event_groups
    return cleaned, removed


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def _write_json(path: Path, data: dict[str, Any]) -> Path | None:
    previous = path.read_bytes() if path.exists() else None
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if previous == encoded:
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    previous_mode: int | None = None
    if previous is not None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        backup.write_bytes(previous)
        previous_mode = stat.S_IMODE(path.stat().st_mode)

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    if previous_mode is not None:
        temporary.chmod(previous_mode)
    temporary.replace(path)
    return backup


def reconcile_adapter(
    adapter: AgentAdapter,
    home: Path,
    command: str,
    install: bool,
) -> IntegrationResult:
    path = adapter.config_path(home)
    if not install and not path.exists():
        return IntegrationResult(
            adapter.key, adapter.display_name, path, False, False, None, 0
        )

    original = _load_json_object(path)
    data = dict(original)
    existing_hooks = data.get("hooks", {})
    if not isinstance(existing_hooks, dict):
        raise ValueError(f'{path} field "hooks" is not an object')

    hooks, _ = _remove_managed_groups(existing_hooks)
    managed_entries = 0
    if install:
        desired = _handler(adapter, command)
        for event in adapter.events:
            groups = hooks.setdefault(event, [])
            if not isinstance(groups, list):
                raise ValueError(f'{path} hook event "{event}" is not an array')
            groups.append({"hooks": [dict(desired)]})
            managed_entries += 1

    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)

    changed = data != original
    backup = _write_json(path, data) if changed else None
    return IntegrationResult(
        adapter.key,
        adapter.display_name,
        path,
        changed,
        install,
        backup,
        managed_entries,
    )


def reconcile_integrations(
    selection: str = "auto",
    *,
    home: Path | None = None,
    command: str | None = None,
    install: bool = True,
) -> list[IntegrationResult]:
    home = Path.home() if home is None else home
    command = runtime_hook_command() if command is None else command
    adapters = parse_agent_selection(selection, home)
    return [
        reconcile_adapter(
            adapter,
            home,
            agent_hook_command(command, adapter.key),
            install,
        )
        for adapter in adapters
    ]


def install_codex_hooks(path: Path, command: str | None = None) -> tuple[Path | None, int]:
    """Compatibility wrapper for the original single-agent installer."""
    home = path.parent
    adapter = replace(ADAPTERS["codex"], config_parts=(path.name,))
    base_command = command or runtime_hook_command()
    result = reconcile_adapter(
        adapter,
        home,
        agent_hook_command(base_command, "codex"),
        True,
    )
    return result.backup, result.managed_entries if result.changed else 0
