"""Deterministic attention rules for missing and unresolved daily loops."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from lifeos.daily.errors import DailyInteractionError
from lifeos.copilot.replanning import ReplanningError, scan_replanning_triggers
from lifeos.daily.execution import load_execution_records
from lifeos.feedback import build_evidence_dataset, diagnose_repeated_avoidance
from lifeos.markdown.parser import parse_markdown_note
from lifeos.planning import PlanningError, load_plan_actions
from lifeos.study import StudySessionService
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

Severity = Literal["info", "attention", "important"]


@dataclass(frozen=True, slots=True)
class AttentionEvidence:
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class SuggestedAction:
    action: str
    label: str


@dataclass(frozen=True, slots=True)
class AttentionItem:
    item_id: str
    kind: str
    severity: Severity
    title: str
    explanation: str
    first_seen: str
    evidence: tuple[AttentionEvidence, ...]
    actions: tuple[SuggestedAction, ...]
    expires_when: str | None = None


@dataclass(frozen=True, slots=True)
class AttentionPreferences:
    morning_checkin: bool = True
    evening_checkin: bool = True
    inbox_days: int = 7
    quiet_until: str | None = None
    snoozed_until: tuple[tuple[str, str], ...] = ()
    dismissed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttentionResult:
    as_of: str
    items: tuple[AttentionItem, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join((kind, *parts)).encode()).hexdigest()[:20]
    return f"{kind}:{digest}"


def _date_value(value: object) -> date | None:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def load_preferences(runtime_dir: Path) -> AttentionPreferences:
    path = runtime_dir / "attention" / "preferences.json"
    if not path.exists():
        return AttentionPreferences()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("preferences must be a mapping")
        snoozed_raw = raw.get("snoozed_until", {})
        dismissed_raw = raw.get("dismissed", [])
        if not isinstance(snoozed_raw, dict) or not isinstance(dismissed_raw, list):
            raise ValueError("invalid attention preference collections")
        return AttentionPreferences(
            morning_checkin=raw.get("morning_checkin", True) is True,
            evening_checkin=raw.get("evening_checkin", True) is True,
            inbox_days=int(raw.get("inbox_days", 7)),
            quiet_until=(
                raw.get("quiet_until") if isinstance(raw.get("quiet_until"), str) else None
            ),
            snoozed_until=tuple(
                sorted((str(key), str(value)) for key, value in snoozed_raw.items())
            ),
            dismissed=tuple(sorted(str(item) for item in dismissed_raw if isinstance(item, str))),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise DailyInteractionError(
            "attention_preferences_corrupt",
            "Attention preferences are corrupt.",
            "Reset the disposable attention preferences.",
        ) from exc


def save_preference(
    runtime_dir: Path,
    *,
    item_id: str | None = None,
    snooze_until: str | None = None,
    dismiss: bool = False,
    morning_checkin: bool | None = None,
    evening_checkin: bool | None = None,
    inbox_days: int | None = None,
) -> AttentionPreferences:
    current = load_preferences(runtime_dir)
    snoozed = dict(current.snoozed_until)
    dismissed = set(current.dismissed)
    if item_id:
        if snooze_until:
            try:
                datetime.fromisoformat(snooze_until)
            except ValueError as exc:
                raise DailyInteractionError(
                    "invalid_preference",
                    "Snooze time must be an ISO datetime.",
                    "Correct the snooze time.",
                ) from exc
            snoozed[item_id] = snooze_until
        if dismiss:
            dismissed.add(item_id)
    if inbox_days is not None and (
        type(inbox_days) is not int or inbox_days < 1 or inbox_days > 365
    ):
        raise DailyInteractionError(
            "invalid_preference",
            "Inbox threshold must be from 1 to 365 days.",
            "Correct the threshold.",
        )
    updated = AttentionPreferences(
        current.morning_checkin if morning_checkin is None else morning_checkin,
        current.evening_checkin if evening_checkin is None else evening_checkin,
        current.inbox_days if inbox_days is None else inbox_days,
        current.quiet_until,
        tuple(sorted(snoozed.items())),
        tuple(sorted(dismissed)),
    )
    path = runtime_dir / "attention" / "preferences.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "morning_checkin": updated.morning_checkin,
                "evening_checkin": updated.evening_checkin,
                "inbox_days": updated.inbox_days,
                "quiet_until": updated.quiet_until,
                "snoozed_until": dict(updated.snoozed_until),
                "dismissed": list(updated.dismissed),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return updated


def _journal_state(vault_root: Path, day: date) -> tuple[bool, bool, dict[str, Any]]:
    try:
        source = read_vault_markdown(vault_root, f"journal/{day.isoformat()}.md")
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return False, False, {}
        raise
    parsed = parse_markdown_note(source.path, content=source.content)
    body = parsed.body.casefold()
    return (
        "## morning check-in" in body or bool(parsed.frontmatter.get("metrics")),
        "## evening check-in" in body,
        dict(parsed.frontmatter),
    )


def _task_actions() -> tuple[SuggestedAction, ...]:
    return (
        SuggestedAction("done", "Done"),
        SuggestedAction("partial", "Partial"),
        SuggestedAction("skipped", "Skipped"),
        SuggestedAction("deferred", "Deferred"),
        SuggestedAction("cancelled", "No longer relevant"),
        SuggestedAction("snooze", "Ask tomorrow"),
        SuggestedAction("dismiss", "Dismiss"),
    )


def evaluate_attention(
    *,
    vault_root: Path,
    runtime_dir: Path,
    as_of: datetime,
    preferences: AttentionPreferences | None = None,
) -> AttentionResult:
    prefs = preferences or load_preferences(runtime_dir)
    day = as_of.date()
    items: list[AttentionItem] = []
    diagnostics: list[str] = []

    try:
        records = load_execution_records(vault_root)
        event_keys = {(record.task_id, record.day) for record in records}
        plan_actions = load_plan_actions(vault_root)
        for action in plan_actions:
            try:
                source = read_vault_markdown(vault_root, action.source_path)
                parsed = parse_markdown_note(source.path, content=source.content)
                tasks = parsed.frontmatter.get("tasks", [])
                raw_task = next(
                    (
                        item
                        for item in tasks
                        if isinstance(item, dict) and item.get("task_id") == action.task_id
                    ),
                    None,
                )
                planned = (
                    _date_value(raw_task.get("planned_for")) if isinstance(raw_task, dict) else None
                )
            except (VaultAccessError, TypeError):
                planned = None
            if (
                planned is not None
                and planned < day
                and (action.task_id, planned) not in event_keys
                and action.status not in {"done", "completed", "cancelled", "archived"}
            ):
                item_id = _stable_id(
                    "unaccounted-task", action.source_path, action.task_id, planned.isoformat()
                )
                items.append(
                    AttentionItem(
                        item_id,
                        "unaccounted_task",
                        "important",
                        f"What happened to {action.title}?",
                        "This planned action has no recorded outcome. Silence is treated as unknown, not skipped.",
                        planned.isoformat(),
                        (
                            AttentionEvidence(
                                action.source_path, f"Planned for {planned.isoformat()}"
                            ),
                        ),
                        _task_actions(),
                        "when an explicit outcome is recorded",
                    )
                )
        active_by_plan: dict[str, list[Any]] = {}
        for action in plan_actions:
            active_by_plan.setdefault(action.source_path, []).append(action)
        for path, actions in active_by_plan.items():
            if actions and not any(
                item.status in {"todo", "active", "pending"} and not item.blocked_by
                for item in actions
            ):
                item_id = _stable_id("plan-no-next", path)
                items.append(
                    AttentionItem(
                        item_id,
                        "plan_no_next_action",
                        "attention",
                        "Plan has no eligible next action",
                        "The active plan cannot contribute an unblocked action to the daily menu.",
                        day.isoformat(),
                        (AttentionEvidence(path, "No active unblocked task"),),
                        (
                            SuggestedAction("replan", "Review with copilot"),
                            SuggestedAction("dismiss", "Dismiss"),
                        ),
                    )
                )
    except (DailyInteractionError, PlanningError, VaultAccessError) as exc:
        diagnostics.append(f"planning: {exc}")

    try:
        dataset = build_evidence_dataset(vault_root, as_of=day)
        for diagnosis in diagnose_repeated_avoidance(observations=dataset.observations, as_of=day):
            if diagnosis.dismissed:
                continue
            items.append(
                AttentionItem(
                    diagnosis.diagnosis_id,
                    "repeated_avoidance",
                    "attention",
                    diagnosis.title,
                    diagnosis.hypothesis,
                    max(diagnosis.evidence_dates).isoformat(),
                    tuple(
                        AttentionEvidence("execution:" + event_id, "Repeated outcome evidence")
                        for event_id in diagnosis.evidence_event_ids
                    ),
                    tuple(
                        SuggestedAction(action, action.replace("_", " ").title())
                        for action in diagnosis.suggested_actions
                    )
                    + (SuggestedAction("dismiss", "Dismiss"),),
                    "when new evidence changes the fingerprint or the task is resolved",
                )
            )
    except (DailyInteractionError, VaultAccessError) as exc:
        diagnostics.append(f"feedback: {exc}")

    try:
        morning, evening, journal_fm = _journal_state(vault_root, day)
        if prefs.morning_checkin and as_of.hour >= 11 and not morning:
            item_id = _stable_id("missing-checkin", day.isoformat(), "morning")
            items.append(
                AttentionItem(
                    item_id,
                    "missing_checkin",
                    "attention",
                    "Morning check-in is missing",
                    "No morning state was recorded today.",
                    day.isoformat(),
                    (
                        AttentionEvidence(
                            f"journal/{day.isoformat()}.md", "Morning check-in absent"
                        ),
                    ),
                    (
                        SuggestedAction("checkin", "Log now"),
                        SuggestedAction("disable", "Stop tracking"),
                        SuggestedAction("snooze", "Ask later"),
                    ),
                )
            )
        if prefs.evening_checkin and as_of.hour >= 21 and not evening:
            item_id = _stable_id("missing-checkin", day.isoformat(), "evening")
            items.append(
                AttentionItem(
                    item_id,
                    "missing_checkin",
                    "attention",
                    "Evening reconciliation is missing",
                    "Today's story has not been closed yet.",
                    day.isoformat(),
                    (
                        AttentionEvidence(
                            f"journal/{day.isoformat()}.md", "Evening check-in absent"
                        ),
                    ),
                    (
                        SuggestedAction("checkin", "Review today"),
                        SuggestedAction("snooze", "Ask tomorrow"),
                        SuggestedAction("disable", "Change frequency"),
                    ),
                )
            )
        required_metrics: list[tuple[str, str]] = []
        for source in iter_vault_markdown(vault_root, roots=("experiments",)):
            parsed = parse_markdown_note(source.path, content=source.content)
            if parsed.frontmatter.get("status") == "active":
                raw = parsed.frontmatter.get("required_metrics", [])
                if isinstance(raw, list):
                    required_metrics.extend(
                        (source.relative_path, metric) for metric in raw if isinstance(metric, str)
                    )
        metrics_raw = journal_fm.get("metrics", {})
        metrics = metrics_raw if isinstance(metrics_raw, dict) else {}
        for path, metric in required_metrics:
            if metric not in metrics:
                item_id = _stable_id("experiment-observation", path, metric, day.isoformat())
                items.append(
                    AttentionItem(
                        item_id,
                        "experiment_missing_observation",
                        "attention",
                        f"Experiment observation missing: {metric}",
                        "An active experiment expects this observation today.",
                        day.isoformat(),
                        (
                            AttentionEvidence(path, f"Requires metric {metric}"),
                            AttentionEvidence(f"journal/{day.isoformat()}.md", "Metric absent"),
                        ),
                        (
                            SuggestedAction("metric", "Log observation"),
                            SuggestedAction("open", "Review experiment"),
                            SuggestedAction("snooze", "Ask tomorrow"),
                        ),
                    )
                )
    except VaultAccessError as exc:
        diagnostics.append(f"journal: {exc}")

    try:
        for session in StudySessionService(
            vault_root=vault_root, runtime_dir=runtime_dir
        ).list_open():
            item_id = _stable_id("unfinished-study", session.session_id)
            items.append(
                AttentionItem(
                    item_id,
                    "unfinished_study_session",
                    "important",
                    "Study session is still open",
                    "A started study workload was not finished or abandoned.",
                    session.started_at,
                    tuple(
                        AttentionEvidence(path, "Selected for this session")
                        for path in session.card_paths
                    ),
                    (
                        SuggestedAction("resume", "Resume"),
                        SuggestedAction("finish", "Finish"),
                        SuggestedAction("abandon", "Abandon"),
                    ),
                    "when the session is finished or abandoned",
                )
            )
    except DailyInteractionError as exc:
        diagnostics.append(f"study-session: {exc}")

    try:
        threshold = day - timedelta(days=prefs.inbox_days)
        for source in iter_vault_markdown(vault_root, roots=("raw",)):
            parsed = parse_markdown_note(source.path, content=source.content)
            if str(parsed.frontmatter.get("status", "")).casefold() != "inbox":
                continue
            captured = _date_value(parsed.frontmatter.get("date")) or _date_value(
                parsed.frontmatter.get("captured_at")
            )
            if captured is not None and captured <= threshold:
                item_id = _stable_id("old-inbox", source.relative_path)
                items.append(
                    AttentionItem(
                        item_id,
                        "old_inbox",
                        "info",
                        "Inbox item is waiting",
                        f"This capture has remained unprocessed for at least {prefs.inbox_days} days.",
                        captured.isoformat(),
                        (
                            AttentionEvidence(
                                source.relative_path,
                                f"Inbox since {captured.isoformat()}",
                            ),
                        ),
                        (
                            SuggestedAction("open", "Process"),
                            SuggestedAction("dismiss", "Dismiss"),
                        ),
                    )
                )
    except VaultAccessError as exc:
        diagnostics.append(f"inbox: {exc}")

    try:
        replanning = scan_replanning_triggers(
            vault_root=vault_root, runtime_dir=runtime_dir, as_of=day
        )
        existing_paths = {
            evidence.path
            for item in items
            if item.kind in {"plan_no_next_action", "repeated_avoidance"}
            for evidence in item.evidence
        }
        severity_map: dict[str, Severity] = {
            "information": "info",
            "attention": "attention",
            "important": "important",
        }
        for trigger in replanning:
            if trigger.target_path in existing_paths and trigger.code in {
                "plan-no-feasible-next-action",
                "repeated-avoidance",
            }:
                continue
            items.append(
                AttentionItem(
                    trigger.trigger_id,
                    "replanning_review",
                    severity_map[trigger.severity],
                    trigger.title,
                    trigger.detail,
                    day.isoformat(),
                    tuple(
                        AttentionEvidence(trigger.target_path, reference)
                        for reference in trigger.evidence_refs
                    )
                    or (AttentionEvidence(trigger.target_path, trigger.code),),
                    (
                        SuggestedAction("replan", "Review with copilot"),
                        SuggestedAction("continue", "Continue unchanged"),
                        SuggestedAction("dismiss", "Dismiss until evidence changes"),
                    ),
                    "when the evidence fingerprint changes or the review is resolved",
                )
            )
    except (ReplanningError, VaultAccessError) as exc:
        diagnostics.append(f"replanning: {exc}")

    # First-class daily reviews are optional until created. Once present, an open
    # phase can surface as a resumable loop without forcing review creation.
    try:
        review_path = f"reviews/daily/{day.isoformat()}.md"
        review_source = read_vault_markdown(vault_root, review_path)
        review_parsed = parse_markdown_note(review_source.path, content=review_source.content)
        phases = review_parsed.frontmatter.get("phases", [])
        if isinstance(phases, list):
            phase_thresholds = {"morning": 11, "evening": 20}
            for phase in phases:
                if not isinstance(phase, dict):
                    continue
                phase_id = phase.get("phase_id")
                state = phase.get("state", "pending")
                if not isinstance(phase_id, str):
                    continue
                threshold_hour = phase_thresholds.get(phase_id)
                if threshold_hour is None or state != "pending" or as_of.hour < threshold_hour:
                    continue
                item_id = _stable_id("daily-review-phase", day.isoformat(), str(phase_id))
                items.append(
                    AttentionItem(
                        item_id,
                        "daily_review_phase",
                        "attention",
                        f"Resume {phase_id} review",
                        f"The canonical daily review exists and its {phase_id} phase is still open.",
                        day.isoformat(),
                        (AttentionEvidence(review_path, f"{phase_id} phase is pending"),),
                        (
                            SuggestedAction("review", "Resume review"),
                            SuggestedAction("snooze", "Ask later"),
                        ),
                        f"when the {phase_id} phase is completed or intentionally skipped",
                    )
                )
    except VaultAccessError as exc:
        if exc.code != "not-found":
            diagnostics.append(f"daily-review: {exc}")

    try:
        week_start = day - timedelta(days=day.weekday())
        iso = week_start.isocalendar()
        weekly_path = f"reviews/weekly/{iso.year}-W{iso.week:02d}.md"
        weekly_source = read_vault_markdown(vault_root, weekly_path)
        weekly_parsed = parse_markdown_note(weekly_source.path, content=weekly_source.content)
        phases = weekly_parsed.frontmatter.get("phases", [])
        pending = (
            any(
                isinstance(phase, dict)
                and phase.get("phase_id") == "weekly"
                and phase.get("state", "pending") == "pending"
                for phase in phases
            )
            if isinstance(phases, list)
            else False
        )
        if pending and (day.weekday() == 6 and as_of.hour >= 17):
            item_id = _stable_id("weekly-review", f"{iso.year}-W{iso.week:02d}")
            items.append(
                AttentionItem(
                    item_id,
                    "weekly_review",
                    "attention",
                    "Resume weekly review",
                    "The canonical weekly review exists and remains open as the ISO week ends.",
                    day.isoformat(),
                    (AttentionEvidence(weekly_path, "Weekly phase is pending"),),
                    (
                        SuggestedAction("review", "Resume review"),
                        SuggestedAction("snooze", "Ask tomorrow"),
                    ),
                    "when the weekly review is completed or intentionally skipped",
                )
            )
    except VaultAccessError as exc:
        if exc.code != "not-found":
            diagnostics.append(f"weekly-review: {exc}")

    snoozed = dict(prefs.snoozed_until)
    dismissed = set(prefs.dismissed)
    filtered: list[AttentionItem] = []
    for item in items:
        if item.item_id in dismissed:
            continue
        until = snoozed.get(item.item_id)
        if until:
            try:
                if datetime.fromisoformat(until) > as_of:
                    continue
            except ValueError:
                diagnostics.append(f"invalid snooze for {item.item_id}")
        filtered.append(item)
    order = {"important": 0, "attention": 1, "info": 2}
    filtered.sort(key=lambda item: (order[item.severity], item.item_id))
    return AttentionResult(as_of.isoformat(), tuple(filtered), tuple(diagnostics))
