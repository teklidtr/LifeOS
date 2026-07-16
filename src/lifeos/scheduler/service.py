"""Opt-in local attention scheduling and privacy-aware desktop notifications."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from lifeos.attention import AttentionItem, evaluate_attention
from lifeos.daily.errors import DailyInteractionError


@dataclass(frozen=True, slots=True)
class ScheduleConfig:
    enabled: bool = False
    timezone: str = "UTC"
    morning: str = "08:30"
    evening: str = "19:30"
    weekly_day: int = 6
    weekly: str = "18:00"
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    privacy: str = "generic"
    grace_hours: int = 6


@dataclass(frozen=True, slots=True)
class Notification:
    notification_id: str
    title: str
    body: str
    open_uri: str
    attention_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerRun:
    evaluated_at: str
    delivered: tuple[Notification, ...]
    suppressed: tuple[str, ...]
    next_check_hint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NotificationAdapter(Protocol):
    def send(self, notification: Notification) -> None: ...


class MemoryNotificationAdapter:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)


class MacOSNotificationAdapter:
    def send(self, notification: Notification) -> None:
        script = "display notification " + json.dumps(notification.body) + " with title " + json.dumps(notification.title)
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


class LinuxNotificationAdapter:
    def send(self, notification: Notification) -> None:
        subprocess.run(["notify-send", notification.title, notification.body], check=True, capture_output=True)


def default_adapter() -> NotificationAdapter:
    system = platform.system()
    if system == "Darwin":
        return MacOSNotificationAdapter()
    if system == "Linux":
        return LinuxNotificationAdapter()
    raise DailyInteractionError(
        "unsupported_platform",
        f"Background notifications are not supported on {system}.",
        "Keep Obsidian open or disable the background service.",
    )


def _parse_clock(value: str, field: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise DailyInteractionError(
            "invalid_schedule",
            f"{field} must be HH:MM.",
            "Correct system/attention-schedule.yml.",
        ) from exc
    return parsed.replace(second=0, microsecond=0)


def load_schedule(vault_root: Path) -> ScheduleConfig:
    path = vault_root / "system" / "attention-schedule.yml"
    if not path.exists():
        return ScheduleConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DailyInteractionError(
            "invalid_schedule",
            "Attention schedule could not be read.",
            "Repair system/attention-schedule.yml.",
        ) from exc
    if not isinstance(raw, dict):
        raise DailyInteractionError("invalid_schedule", "Attention schedule must be a mapping.", "Repair the schedule file.")
    allowed = {"enabled", "timezone", "morning", "evening", "weekly_day", "weekly", "quiet_start", "quiet_end", "privacy", "grace_hours"}
    unknown = set(raw) - allowed
    if unknown:
        raise DailyInteractionError("invalid_schedule", "Attention schedule has unknown fields.", "Remove unsupported fields.", {"fields": sorted(unknown)})
    config = ScheduleConfig(**raw)
    if type(config.enabled) is not bool or config.privacy not in {"generic", "titles"}:
        raise DailyInteractionError("invalid_schedule", "Schedule values are invalid.", "Repair the schedule file.")
    if type(config.weekly_day) is not int or not 0 <= config.weekly_day <= 6:
        raise DailyInteractionError("invalid_schedule", "weekly_day must be 0 through 6.", "Correct the weekday.")
    if type(config.grace_hours) is not int or not 0 <= config.grace_hours <= 24:
        raise DailyInteractionError("invalid_schedule", "grace_hours must be 0 through 24.", "Correct the grace period.")
    for field in ("morning", "evening", "weekly", "quiet_start", "quiet_end"):
        _parse_clock(getattr(config, field), field)
    try:
        ZoneInfo(config.timezone)
    except ZoneInfoNotFoundError as exc:
        raise DailyInteractionError("invalid_schedule", "Schedule timezone is unknown.", "Use an IANA timezone name.") from exc
    return config


def save_schedule(vault_root: Path, config: ScheduleConfig) -> Path:
    system = vault_root / "system"
    system.mkdir(parents=True, exist_ok=True)
    path = system / "attention-schedule.yml"
    temp = path.with_suffix(".tmp")
    temp.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")
    os.replace(temp, path)
    return path


def _in_quiet_hours(local: datetime, config: ScheduleConfig) -> bool:
    start = _parse_clock(config.quiet_start, "quiet_start")
    end = _parse_clock(config.quiet_end, "quiet_end")
    current = local.time().replace(tzinfo=None)
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _window_due(local: datetime, clock: str, grace_hours: int) -> bool:
    scheduled = datetime.combine(local.date(), _parse_clock(clock, "schedule"), tzinfo=local.tzinfo)
    return scheduled <= local <= scheduled + timedelta(hours=grace_hours)


class AttentionScheduler:
    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        vault_name: str,
        adapter: NotificationAdapter,
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.vault_name = vault_name
        self.adapter = adapter
        self.state_path = runtime_dir / "scheduler" / "delivery.json"

    def run(self, now: datetime) -> SchedulerRun:
        config = load_schedule(self.vault_root)
        if not config.enabled:
            return SchedulerRun(now.isoformat(), (), ("scheduler-disabled",), "Enable the schedule in Obsidian settings.")
        zone = ZoneInfo(config.timezone)
        local = now.astimezone(zone)
        if _in_quiet_hours(local, config):
            return SchedulerRun(now.isoformat(), (), ("quiet-hours",), f"Quiet hours end at {config.quiet_end}.")
        due_routines: list[str] = []
        if _window_due(local, config.morning, config.grace_hours):
            due_routines.append("morning")
        if _window_due(local, config.evening, config.grace_hours):
            due_routines.append("evening")
        if local.weekday() == config.weekly_day and _window_due(local, config.weekly, config.grace_hours):
            due_routines.append("weekly")
        attention = evaluate_attention(vault_root=self.vault_root, runtime_dir=self.runtime_dir, as_of=local)
        if attention.items:
            due_routines.append("condition")
        state = self._load_state()
        delivered: list[Notification] = []
        suppressed: list[str] = []
        for routine in dict.fromkeys(due_routines):
            item = self._pick_item(attention.items, routine)
            item_key = item.item_id if item else "none"
            notification_id = f"{routine}:{local.date().isoformat()}:{item_key}"
            if notification_id in state["delivered"]:
                suppressed.append(notification_id)
                continue
            title = {
                "morning": "LifeOS morning check-in",
                "evening": "LifeOS evening reconciliation",
                "weekly": "LifeOS weekly review",
                "condition": "LifeOS needs your attention",
            }[routine]
            body = (
                item.title
                if item is not None and config.privacy == "titles"
                else "Open LifeOS in Obsidian to review an outstanding item."
            )
            context = item.kind if item else routine
            uri = f"obsidian://open?vault={quote(self.vault_name)}&file={quote('LifeOS Today')}&context={quote(context)}"
            notification = Notification(notification_id, title, body, uri, item.item_id if item else None)
            self.adapter.send(notification)
            delivered.append(notification)
            state["delivered"].append(notification_id)
        state["last_run"] = local.isoformat()
        self._save_state(state)
        return SchedulerRun(now.isoformat(), tuple(delivered), tuple(suppressed), "Run again at the next configured window or hourly condition check.")

    def _pick_item(self, items: tuple[AttentionItem, ...], routine: str) -> AttentionItem | None:
        if routine == "morning":
            return next((item for item in items if item.title.startswith("Morning")), None)
        if routine == "evening":
            return next((item for item in items if item.title.startswith("Evening") or item.kind == "unaccounted_task"), None)
        return items[0] if items else None

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"delivered": [], "last_run": None}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("delivered"), list):
                raise ValueError
            return raw
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise DailyInteractionError("scheduler_state_corrupt", "Scheduler delivery state is corrupt.", "Reset disposable scheduler state.") from exc

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, self.state_path)


class BackgroundServiceInstaller:
    """Creates reversible local service descriptors without executing them silently."""

    def __init__(self, runtime_dir: Path) -> None:
        self.root = runtime_dir / "scheduler" / "service"

    def install(self, *, command: tuple[str, ...], platform_name: str | None = None) -> Path:
        system = platform_name or platform.system()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / ("com.lifeos.attention.plist" if system == "Darwin" else "lifeos-attention.service")
        document = {"platform": system, "command": list(command), "installed": True}
        path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path

    def uninstall(self) -> None:
        if self.root.exists():
            for path in self.root.iterdir():
                path.unlink()
            self.root.rmdir()

    def status(self) -> dict[str, Any]:
        files = tuple(path.name for path in self.root.iterdir()) if self.root.exists() else ()
        return {"installed": bool(files), "descriptors": files}
