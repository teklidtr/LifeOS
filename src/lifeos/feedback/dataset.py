"""Deterministic execution-feedback evidence rebuilding."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from lifeos._atomic_write import AtomicWriteError, atomic_write_file_secure
from lifeos.feedback.models import (
    EvidenceDataset,
    EvidenceDatasetStatus,
    EvidenceOutcome,
    FeedbackDiagnostic,
    FeedbackObservation,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

DATASET_SCHEMA_VERSION = 1
_SUPPORTED_EVENT_SCHEMA = 1
_OUTCOMES = frozenset({"started", "done", "partial", "skipped", "deferred", "cancelled", "unaccounted"})
_LEVELS = frozenset({"low", "medium", "high"})


def _stable_hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _date_value(value: object) -> date | None:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _datetime_value(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _optional_int(raw: dict[str, Any], key: str, *, low: int, high: int) -> tuple[int | None, bool]:
    value = raw.get(key)
    if value is None:
        return None, True
    if type(value) is not int or value < low or value > high:
        return None, False
    return value, True


def _optional_fraction(raw: dict[str, Any], outcome: str) -> tuple[float | None, bool]:
    value = raw.get("completion_fraction")
    if value is None:
        defaults = {"done": 1.0, "partial": None, "started": None, "skipped": 0.0, "deferred": 0.0, "cancelled": None, "unaccounted": None}
        return defaults[outcome], True
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, False
    result = float(value)
    return (result, 0.0 <= result <= 1.0)


def _task_snapshot(raw_task: dict[str, Any] | None, raw_event: dict[str, Any]) -> dict[str, Any]:
    task = raw_task or {}
    return {
        "task_title": str(raw_event.get("task_title") or task.get("title") or raw_event.get("task_id") or ""),
        "task_shape": str(raw_event.get("task_shape") or task.get("task_shape") or task.get("template") or "unspecified"),
        "mode": str(raw_event.get("mode") or task.get("mode") or "unspecified").casefold(),
        "task_energy": raw_event.get("task_energy", task.get("energy")),
        "task_motivation": raw_event.get("task_motivation", task.get("motivation")),
        "blocked": bool(raw_event.get("blocked", bool(task.get("blocked_by")))) if raw_event.get("blocked") is not None or task else None,
        "planned_minutes": raw_event.get("planned_minutes", task.get("duration")),
    }


def _canonical_event(
    *,
    raw: dict[str, Any],
    source_path: str,
    source_hash: str,
    source_index: int,
    plan_id: str,
    goal_id: str,
    raw_task: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, tuple[FeedbackDiagnostic, ...]]:
    diagnostics: list[FeedbackDiagnostic] = []
    event_id = raw.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        diagnostics.append(FeedbackDiagnostic("invalid_event_id", "Execution event requires a non-empty event_id.", source_path))
        return None, tuple(diagnostics)
    event_id = event_id.strip()
    schema = raw.get("schema_version", 1)
    if type(schema) is not int or schema != _SUPPORTED_EVENT_SCHEMA:
        diagnostics.append(FeedbackDiagnostic("unsupported_event_schema", f"Execution event {event_id} uses unsupported schema {schema!r}.", source_path, event_id))
        return None, tuple(diagnostics)
    task_id = raw.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        diagnostics.append(FeedbackDiagnostic("invalid_task_id", f"Execution event {event_id} requires a task_id.", source_path, event_id))
        return None, tuple(diagnostics)
    outcome = raw.get("outcome")
    if not isinstance(outcome, str) or outcome not in _OUTCOMES:
        diagnostics.append(FeedbackDiagnostic("invalid_outcome", f"Execution event {event_id} has an invalid outcome.", source_path, event_id))
        return None, tuple(diagnostics)
    day = _date_value(raw.get("date"))
    if day is None:
        diagnostics.append(FeedbackDiagnostic("invalid_event_date", f"Execution event {event_id} requires an ISO date.", source_path, event_id))
        return None, tuple(diagnostics)
    snapshot = _task_snapshot(raw_task, raw)
    planned, planned_ok = _optional_int({"planned_minutes": snapshot["planned_minutes"]}, "planned_minutes", low=0, high=1440)
    actual, actual_ok = _optional_int(raw, "actual_minutes", low=0, high=1440)
    if not planned_ok or not actual_ok:
        diagnostics.append(FeedbackDiagnostic("invalid_duration", f"Execution event {event_id} has an impossible duration.", source_path, event_id))
        return None, tuple(diagnostics)
    fraction, fraction_ok = _optional_fraction(raw, outcome)
    if not fraction_ok:
        diagnostics.append(FeedbackDiagnostic("invalid_completion_fraction", f"Execution event {event_id} has an invalid completion fraction.", source_path, event_id))
        return None, tuple(diagnostics)
    for field in ("energy_before", "energy_after", "motivation_before"):
        value = raw.get(field)
        if value is not None and value not in _LEVELS:
            diagnostics.append(FeedbackDiagnostic("invalid_capacity_level", f"Execution event {event_id} has invalid {field}.", source_path, event_id))
            return None, tuple(diagnostics)
    for field in ("task_energy", "task_motivation"):
        value = snapshot[field]
        if value is not None and value not in _LEVELS:
            diagnostics.append(FeedbackDiagnostic("invalid_task_level", f"Execution event {event_id} has invalid {field}.", source_path, event_id))
            snapshot[field] = None
    started = _datetime_value(raw.get("started_at"))
    ended = _datetime_value(raw.get("ended_at"))
    if raw.get("started_at") and started is None or raw.get("ended_at") and ended is None:
        diagnostics.append(FeedbackDiagnostic("invalid_chronology", f"Execution event {event_id} has an invalid timestamp.", source_path, event_id))
        return None, tuple(diagnostics)
    if started is not None and ended is not None:
        try:
            if ended < started:
                diagnostics.append(FeedbackDiagnostic("invalid_chronology", f"Execution event {event_id} ends before it starts.", source_path, event_id))
                return None, tuple(diagnostics)
        except TypeError:
            diagnostics.append(FeedbackDiagnostic("invalid_chronology", f"Execution event {event_id} mixes timezone-aware and naive timestamps.", source_path, event_id))
            return None, tuple(diagnostics)
    return {
        "event_id": event_id,
        "schema_version": schema,
        "task_id": task_id.strip(),
        "outcome": outcome,
        "day": day,
        "source_path": source_path,
        "source_hash": source_hash,
        "source_index": source_index,
        "plan_id": plan_id,
        "goal_id": goal_id,
        "task_title": snapshot["task_title"],
        "task_shape": snapshot["task_shape"],
        "mode": snapshot["mode"],
        "task_energy": snapshot["task_energy"],
        "task_motivation": snapshot["task_motivation"],
        "blocked": snapshot["blocked"],
        "planned_minutes": planned,
        "actual_minutes": actual,
        "completion_fraction": fraction,
        "energy_before": raw.get("energy_before"),
        "energy_after": raw.get("energy_after"),
        "motivation_before": raw.get("motivation_before"),
        "started_at": raw.get("started_at") if isinstance(raw.get("started_at"), str) else None,
        "ended_at": raw.get("ended_at") if isinstance(raw.get("ended_at"), str) else None,
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else None,
        "corrects_event_id": raw.get("corrects_event_id") if isinstance(raw.get("corrects_event_id"), str) else None,
        "retracts_event_id": raw.get("retracts_event_id") if isinstance(raw.get("retracts_event_id"), str) else None,
    }, tuple(diagnostics)


def build_evidence_dataset(vault_root: Path, *, as_of: date | None = None, excluded_event_ids: tuple[str, ...] = ()) -> EvidenceDataset:
    diagnostics: list[FeedbackDiagnostic] = []
    events: list[dict[str, Any]] = []
    source_facts: list[str] = []
    try:
        sources = iter_vault_markdown(vault_root, roots=("plans",))
    except VaultAccessError as exc:
        return EvidenceDataset(DATASET_SCHEMA_VERSION, as_of or date.today(), "", (), (FeedbackDiagnostic("storage_unavailable", str(exc)),), (), 0, 0)
    for source in sources:
        parsed = parse_markdown_note(source.path, content=source.content)
        if parsed.frontmatter.get("type") != "plan":
            continue
        source_hash = _content_hash(source.content)
        source_facts.append(f"{source.relative_path}:{source_hash}")
        plan_id = str(parsed.frontmatter.get("id") or Path(source.relative_path).stem)
        goal = parsed.frontmatter.get("goal")
        goal_id = goal.strip() if isinstance(goal, str) else ""
        raw_tasks = parsed.frontmatter.get("tasks", [])
        task_map = {
            item.get("task_id"): item
            for item in raw_tasks
            if isinstance(raw_tasks, list) and isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        history = parsed.frontmatter.get("execution_history", [])
        if history is None:
            continue
        if not isinstance(history, list):
            diagnostics.append(FeedbackDiagnostic("invalid_execution_history", "execution_history must be a list.", source.relative_path))
            continue
        for index, raw in enumerate(history):
            if not isinstance(raw, dict):
                diagnostics.append(FeedbackDiagnostic("invalid_execution_event", "Execution event must be a mapping.", source.relative_path))
                continue
            task_id = raw.get("task_id")
            raw_task = task_map.get(task_id) if isinstance(task_id, str) else None
            event, found = _canonical_event(raw=raw, source_path=source.relative_path, source_hash=source_hash, source_index=index, plan_id=plan_id, goal_id=goal_id, raw_task=raw_task)
            diagnostics.extend(found)
            if event is not None:
                if raw_task is None:
                    diagnostics.append(FeedbackDiagnostic("orphaned_task_reference", f"Execution event {event['event_id']} refers to a task no longer present in the plan.", source.relative_path, event["event_id"], "warning"))
                events.append(event)

    by_id: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for event in events:
        event_id = cast(str, event["event_id"])
        if event_id in by_id:
            duplicate_ids.add(event_id)
        else:
            by_id[event_id] = event
    for event_id in sorted(duplicate_ids):
        diagnostics.append(FeedbackDiagnostic("duplicate_event_id", f"Duplicate execution event ID: {event_id}", event_id=event_id))
        by_id.pop(event_id, None)

    correction_children: dict[str, list[str]] = {}
    retractions: dict[str, str] = {}
    for event_id, event in by_id.items():
        corrects = event.get("corrects_event_id")
        retracts = event.get("retracts_event_id")
        if corrects:
            correction_children.setdefault(corrects, []).append(event_id)
        if retracts:
            if retracts in retractions:
                diagnostics.append(FeedbackDiagnostic("conflicting_retractions", f"Multiple events retract {retracts}.", event_id=event_id))
            retractions[retracts] = event_id
    conflicted: set[str] = set()
    for target, children in correction_children.items():
        if len(children) > 1:
            conflicted.update(children)
            conflicted.add(target)
            diagnostics.append(FeedbackDiagnostic("conflicting_corrections", f"Multiple corrections target {target}: {', '.join(sorted(children))}.", event_id=target))

    excluded = set(excluded_event_ids)
    observations: list[FeedbackObservation] = []
    corrected_count = 0
    retracted_count = 0
    replaced_ids = set(correction_children)
    retracted_ids = set(retractions)
    for event_id, event in sorted(by_id.items()):
        if event_id in conflicted or event_id in retracted_ids or event_id in replaced_ids or event.get("retracts_event_id"):
            if event_id in retracted_ids:
                retracted_count += 1
            continue
        lineage: list[str] = []
        cursor = event
        seen_lineage: set[str] = set()
        while cursor.get("corrects_event_id"):
            parent = cast(str, cursor["corrects_event_id"])
            if parent in seen_lineage or parent not in by_id:
                diagnostics.append(FeedbackDiagnostic("invalid_correction_lineage", f"Correction {event_id} has missing or cyclic lineage.", event_id=event_id))
                lineage = []
                break
            seen_lineage.add(parent)
            lineage.append(parent)
            cursor = by_id[parent]
        if event.get("corrects_event_id"):
            corrected_count += 1
        observation_id = _stable_hash(event["source_path"], event_id, event["source_hash"], str(event["source_index"]))
        observations.append(FeedbackObservation(
            schema_version=DATASET_SCHEMA_VERSION,
            observation_id=observation_id,
            event_id=event_id,
            source_path=event["source_path"],
            source_hash=event["source_hash"],
            source_index=event["source_index"],
            day=event["day"],
            plan_id=event["plan_id"],
            goal_id=event["goal_id"],
            task_id=event["task_id"],
            task_title=event["task_title"],
            task_shape=event["task_shape"],
            mode=event["mode"],
            task_energy=event["task_energy"],
            task_motivation=event["task_motivation"],
            blocked=event["blocked"],
            outcome=cast(EvidenceOutcome, event["outcome"]),
            completion_fraction=event["completion_fraction"],
            planned_minutes=event["planned_minutes"],
            actual_minutes=event["actual_minutes"],
            energy_before=event["energy_before"],
            energy_after=event["energy_after"],
            motivation_before=event["motivation_before"],
            started_at=event["started_at"],
            ended_at=event["ended_at"],
            reason=event["reason"],
            correction_lineage=tuple(lineage),
            excluded=event_id in excluded,
        ))
    observations.sort(key=lambda item: (item.day, item.source_path, item.task_id, item.event_id))
    diagnostics.sort(key=lambda item: (item.source_path or "", item.event_id or "", item.code, item.message))
    fingerprint = _stable_hash(*(sorted(source_facts) + ["excluded:" + ",".join(sorted(excluded))]))
    return EvidenceDataset(
        DATASET_SCHEMA_VERSION,
        as_of or date.today(),
        fingerprint,
        tuple(observations),
        tuple(diagnostics),
        tuple(sorted(excluded)),
        corrected_count,
        retracted_count,
    )


def serialize_dataset(dataset: EvidenceDataset) -> str:
    return json.dumps(dataset.to_dict(), sort_keys=True, default=str, ensure_ascii=False, indent=2) + "\n"


def rebuild_evidence_dataset(vault_root: Path, runtime_dir: Path, *, as_of: date | None = None, excluded_event_ids: tuple[str, ...] = ()) -> tuple[EvidenceDataset, EvidenceDatasetStatus]:
    dataset = build_evidence_dataset(vault_root, as_of=as_of, excluded_event_ids=excluded_event_ids)
    target = runtime_dir / "feedback" / "evidence-v1.json"
    serialized = serialize_dataset(dataset)
    reused = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_text(encoding="utf-8") == serialized:
            reused = True
        else:
            dir_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                atomic_write_file_secure(dir_fd, target.name, serialized.encode("utf-8"))
            finally:
                os.close(dir_fd)
    except (OSError, AtomicWriteError):
        status = EvidenceDatasetStatus("unavailable", DATASET_SCHEMA_VERSION, len(dataset.observations), len(dataset.diagnostics), len(dataset.excluded_event_ids), dataset.corrected_event_count, dataset.retracted_event_count, dataset.source_fingerprint, str(target), False)
        return dataset, status
    state = "empty" if not dataset.observations and not dataset.diagnostics else "diagnostic" if any(item.severity == "error" for item in dataset.diagnostics) else "ready"
    return dataset, EvidenceDatasetStatus(state, DATASET_SCHEMA_VERSION, len(dataset.observations), len(dataset.diagnostics), len(dataset.excluded_event_ids), dataset.corrected_event_count, dataset.retracted_event_count, dataset.source_fingerprint, str(target), reused)


def load_cached_dataset(runtime_dir: Path) -> EvidenceDataset | None:
    path = runtime_dir / "feedback" / "evidence-v1.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema_version") != DATASET_SCHEMA_VERSION:
        return None
    try:
        observations = tuple(
            FeedbackObservation(
                **{
                    **item,
                    "day": date.fromisoformat(item["day"]),
                    "correction_lineage": tuple(item.get("correction_lineage", ())),
                }
            )
            for item in raw["observations"]
        )
        diagnostics = tuple(FeedbackDiagnostic(**item) for item in raw.get("diagnostics", ()))
        return EvidenceDataset(
            schema_version=raw["schema_version"],
            as_of=date.fromisoformat(raw["as_of"]),
            source_fingerprint=raw["source_fingerprint"],
            observations=observations,
            diagnostics=diagnostics,
            excluded_event_ids=tuple(raw.get("excluded_event_ids", ())),
            corrected_event_count=raw.get("corrected_event_count", 0),
            retracted_event_count=raw.get("retracted_event_count", 0),
        )
    except (KeyError, TypeError, ValueError):
        return None
