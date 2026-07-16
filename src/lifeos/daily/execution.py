"""Canonical execution-history loading and deterministic normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lifeos.daily.contracts import Level, Outcome
from lifeos.daily.errors import DailyInteractionError
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    event_id: str
    plan_path: str
    plan_id: str
    task_id: str
    outcome: Outcome
    day: date
    actor: str
    planned_minutes: int | None = None
    actual_minutes: int | None = None
    energy_before: Level | None = None
    energy_after: Level | None = None
    motivation_before: Level | None = None
    difficulty: int | None = None
    satisfaction: int | None = None
    reason: str | None = None
    note: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    source_ref: str | None = None


def _date(value: object, *, path: str) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise DailyInteractionError("invalid_execution_history", f"{path}: execution date is invalid.", "Repair the execution record.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DailyInteractionError("invalid_execution_history", f"{path}: execution date is invalid.", "Repair the execution record.") from exc


def _optional_int(event: dict[str, Any], key: str, *, low: int, high: int, path: str) -> int | None:
    value = event.get(key)
    if value is None:
        return None
    if type(value) is not int or value < low or value > high:
        raise DailyInteractionError("invalid_execution_history", f"{path}: {key} must be from {low} to {high}.", "Repair the execution record.")
    return value


def load_execution_records(vault_root: Path) -> tuple[ExecutionRecord, ...]:
    records: list[ExecutionRecord] = []
    seen: set[str] = set()
    try:
        sources = iter_vault_markdown(vault_root, roots=("plans",))
    except VaultAccessError as exc:
        raise DailyInteractionError("storage_unavailable", str(exc), "Check vault storage.") from exc
    for source in sources:
        parsed = parse_markdown_note(source.path, content=source.content)
        if parsed.frontmatter.get("type") != "plan":
            continue
        raw_history = parsed.frontmatter.get("execution_history", [])
        if raw_history is None:
            continue
        if not isinstance(raw_history, list):
            raise DailyInteractionError("invalid_execution_history", f"{source.relative_path}: execution_history must be a list.", "Repair the plan note.")
        plan_id = str(parsed.frontmatter.get("id") or Path(source.relative_path).stem)
        for raw in raw_history:
            if not isinstance(raw, dict):
                raise DailyInteractionError("invalid_execution_history", f"{source.relative_path}: execution event must be a mapping.", "Repair the plan note.")
            event_id = raw.get("event_id")
            task_id = raw.get("task_id")
            outcome = raw.get("outcome")
            actor = raw.get("actor")
            if not all(isinstance(value, str) and value.strip() for value in (event_id, task_id, outcome, actor)):
                raise DailyInteractionError("invalid_execution_history", f"{source.relative_path}: execution identity is invalid.", "Repair the plan note.")
            if event_id in seen:
                raise DailyInteractionError("duplicate_execution_event", f"Duplicate execution event: {event_id}", "Use unique event IDs.")
            seen.add(event_id)
            if outcome not in {"started", "done", "partial", "skipped", "deferred", "cancelled"}:
                raise DailyInteractionError("invalid_execution_history", f"{source.relative_path}: unknown outcome {outcome}.", "Repair the plan note.")
            levels: dict[str, Level | None] = {}
            for key in ("energy_before", "energy_after", "motivation_before"):
                value = raw.get(key)
                if value is not None and value not in {"low", "medium", "high"}:
                    raise DailyInteractionError("invalid_execution_history", f"{source.relative_path}: {key} is invalid.", "Repair the plan note.")
                levels[key] = value
            records.append(ExecutionRecord(
                event_id=event_id,
                plan_path=source.relative_path,
                plan_id=plan_id,
                task_id=task_id,
                outcome=outcome,
                day=_date(raw.get("date"), path=source.relative_path),
                actor=actor,
                planned_minutes=_optional_int(raw, "planned_minutes", low=0, high=1440, path=source.relative_path),
                actual_minutes=_optional_int(raw, "actual_minutes", low=0, high=1440, path=source.relative_path),
                energy_before=levels["energy_before"],
                energy_after=levels["energy_after"],
                motivation_before=levels["motivation_before"],
                difficulty=_optional_int(raw, "difficulty", low=1, high=10, path=source.relative_path),
                satisfaction=_optional_int(raw, "satisfaction", low=1, high=10, path=source.relative_path),
                reason=raw.get("reason") if isinstance(raw.get("reason"), str) else None,
                note=raw.get("note") if isinstance(raw.get("note"), str) else None,
                started_at=raw.get("started_at") if isinstance(raw.get("started_at"), str) else None,
                ended_at=raw.get("ended_at") if isinstance(raw.get("ended_at"), str) else None,
                source_ref=raw.get("source_ref") if isinstance(raw.get("source_ref"), str) else None,
            ))
    return tuple(sorted(records, key=lambda item: (item.day, item.plan_path, item.task_id, item.event_id)))


def execution_index(vault_root: Path) -> dict[str, tuple[ExecutionRecord, ...]]:
    grouped: dict[str, list[ExecutionRecord]] = {}
    for record in load_execution_records(vault_root):
        grouped.setdefault(record.task_id, []).append(record)
    return {key: tuple(value) for key, value in sorted(grouped.items())}
