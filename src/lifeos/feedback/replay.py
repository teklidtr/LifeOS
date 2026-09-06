"""Read-only historical replay for baseline and adaptive daily menus."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable, Literal

from lifeos.feedback.models import FeedbackObservation
from lifeos.feedback.planner import ADAPTIVE_POLICY_VERSION, build_adaptive_menu
from lifeos.planning import PlanningAction

REPLAY_SCHEMA_VERSION = 1
ReplayMode = Literal["off", "shadow", "active"]


@dataclass(frozen=True, slots=True)
class ReplayContext:
    day: date
    available_minutes: int = 120
    energy: str = "medium"
    motivation: str = "medium"
    mode_filter: str | None = None
    time_window: str | None = None


@dataclass(frozen=True, slots=True)
class ReplayMenuMetrics:
    selected_task_ids: tuple[str, ...]
    selected_minutes: int
    unused_minutes: int
    actual_minutes: int | None
    overflow_minutes: int | None
    explicit_outcomes: int
    missing_outcomes: int
    completion_fraction: float | None
    mean_absolute_estimate_error: float | None
    explanation_coverage: float


@dataclass(frozen=True, slots=True)
class ReplayDayResult:
    day: date
    baseline: ReplayMenuMetrics
    adaptive: ReplayMenuMetrics
    changed_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalReplayResult:
    schema_version: int
    adaptive_policy_version: int
    mode: ReplayMode
    days: tuple[ReplayDayResult, ...]
    source_fingerprint: str
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _selected_items(menu: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = menu.get("items", ())
    return tuple(item for item in raw if isinstance(item, dict))


def _metrics(
    *,
    menu: dict[str, Any],
    context: ReplayContext,
    observations: tuple[FeedbackObservation, ...],
    reason_by_task: dict[str, tuple[str, ...]],
) -> ReplayMenuMetrics:
    items = _selected_items(menu)
    selected_ids = tuple(str(item.get("task_id")) for item in items)
    selected_minutes = int(menu.get("selected_minutes", 0))
    by_task: dict[str, FeedbackObservation] = {}
    for item in observations:
        if item.day != context.day or item.excluded or item.task_id not in selected_ids:
            continue
        current = by_task.get(item.task_id)
        if current is None or (item.source_index, item.event_id) > (
            current.source_index,
            current.event_id,
        ):
            by_task[item.task_id] = item

    explicit = tuple(by_task[task_id] for task_id in selected_ids if task_id in by_task)
    actual_values = [item.actual_minutes for item in explicit if item.actual_minutes is not None]
    actual_minutes = sum(actual_values) if actual_values else None
    overflow = (
        max(0, actual_minutes - context.available_minutes) if actual_minutes is not None else None
    )
    fractions = [
        item.completion_fraction for item in explicit if item.completion_fraction is not None
    ]
    completion = round(sum(fractions) / len(fractions), 4) if fractions else None
    errors = [
        abs(item.actual_minutes - item.planned_minutes)
        for item in explicit
        if item.actual_minutes is not None and item.planned_minutes is not None
    ]
    error = round(sum(errors) / len(errors), 4) if errors else None
    explained = sum(bool(reason_by_task.get(task_id)) for task_id in selected_ids)
    coverage = round(explained / len(selected_ids), 4) if selected_ids else 1.0
    return ReplayMenuMetrics(
        selected_ids,
        selected_minutes,
        max(0, context.available_minutes - selected_minutes),
        actual_minutes,
        overflow,
        len(explicit),
        len(selected_ids) - len(explicit),
        completion,
        error,
        coverage,
    )


def replay_history(
    *,
    actions: Iterable[PlanningAction],
    observations: Iterable[FeedbackObservation],
    contexts: Iterable[ReplayContext],
    mode: ReplayMode = "shadow",
    disabled_dimensions: tuple[str, ...] = (),
    dismissed_diagnosis_fingerprints: tuple[str, ...] = (),
) -> HistoricalReplayResult:
    """Replay historical menus without writing canonical or derived state.

    Metrics remain separate on purpose. No universal productivity score is
    calculated, and missing outcomes remain missing rather than becoming zeroes.
    """

    action_items = tuple(sorted(actions, key=lambda item: item.task_id))
    observation_items = tuple(sorted(observations, key=lambda item: (item.day, item.event_id)))
    results: list[ReplayDayResult] = []
    context_items = tuple(sorted(contexts, key=lambda item: item.day))
    for context in context_items:
        history = tuple(item for item in observation_items if item.day < context.day)
        visible = tuple(item for item in observation_items if item.day <= context.day)
        plan = build_adaptive_menu(
            actions=action_items,
            observations=history,
            as_of=context.day,
            available_minutes=context.available_minutes,
            energy=context.energy,
            motivation=context.motivation,
            mode_filter=context.mode_filter,
            adaptive_mode=mode,
            time_window=context.time_window,
            disabled_dimensions=disabled_dimensions,
            dismissed_diagnosis_fingerprints=dismissed_diagnosis_fingerprints,
        )
        reasons = {
            item.task_id: item.reason_codes for item in plan.adjustments if item.reason_codes
        }
        baseline = _metrics(
            menu=plan.baseline,
            context=context,
            observations=visible,
            reason_by_task={},
        )
        adaptive = _metrics(
            menu=plan.adaptive,
            context=context,
            observations=visible,
            reason_by_task=reasons,
        )
        changed = tuple(
            sorted(
                {
                    item.task_id
                    for item in plan.deltas
                    if item.baseline_selected != item.adaptive_selected
                    or item.declared_minutes != item.effective_minutes
                }
            )
        )
        results.append(ReplayDayResult(context.day, baseline, adaptive, changed))
    fingerprint_payload = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "adaptive_policy_version": ADAPTIVE_POLICY_VERSION,
        "mode": mode,
        "disabled_dimensions": sorted(set(disabled_dimensions)),
        "dismissed_diagnosis_fingerprints": sorted(set(dismissed_diagnosis_fingerprints)),
        "actions": [asdict(item) for item in action_items],
        "observations": [item.to_dict() for item in observation_items],
        "contexts": [asdict(item) for item in context_items],
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return HistoricalReplayResult(
        REPLAY_SCHEMA_VERSION,
        ADAPTIVE_POLICY_VERSION,
        mode,
        tuple(results),
        fingerprint,
        (
            "Historical replay is descriptive and noncausal. Missing outcomes are "
            "reported separately and are not treated as failures."
        ),
    )
