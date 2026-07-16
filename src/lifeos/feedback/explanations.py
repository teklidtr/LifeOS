"""Stable adaptive-planner explanations and counterfactuals."""

from __future__ import annotations

from typing import Iterable

from lifeos.feedback.models import AdaptivePlanResult, PlannerCounterfactual, PlannerExplanation
from lifeos.planning import PlanningAction

EXPLANATION_SCHEMA_VERSION = 1
_REASON_TEXT = {
    "duration-calibrated": "Historical explicit durations produced a bounded calibrated estimate.",
    "capacity-fit-buffer": "Tentative capacity-fit evidence changed the effective time buffer.",
    "avoidance-uncertainty-buffer": "Repeated outcomes added a small uncertainty buffer rather than cancelling the task.",
    "duration-cap-applied": "The policy cap limited the adaptive duration change.",
    "baseline-selected": "The baseline bounded planner selected this task.",
    "adaptive-selected": "The adaptive bounded planner selected this task.",
    "baseline-only": "The task appears only in the baseline selection.",
    "adaptive-only": "The task appears only in the adaptive selection.",
    "not-selected": "Neither planner selected the task within the current explicit constraints.",
}


def _items(menu: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw = menu.get("items", ())
    return tuple(item for item in raw if isinstance(item, dict)) if isinstance(raw, (tuple, list)) else ()


def _rank(menu: dict[str, object], task_id: str) -> int | None:
    for index, item in enumerate(_items(menu), start=1):
        if item.get("task_id") == task_id:
            return index
    return None


def explain_adaptive_result(
    *,
    result: AdaptivePlanResult,
    actions: Iterable[PlanningAction],
    task_id: str,
) -> PlannerExplanation:
    action = next((item for item in actions if item.task_id == task_id), None)
    adjustment = next((item for item in result.adjustments if item.task_id == task_id), None)
    if action is None or adjustment is None:
        raise KeyError(f"Unknown task: {task_id}")
    baseline_rank = _rank(result.baseline, task_id)
    adaptive_rank = _rank(result.adaptive, task_id)
    reason_codes = list(adjustment.reason_codes)
    if baseline_rank is not None:
        reason_codes.append("baseline-selected")
    if adaptive_rank is not None:
        reason_codes.append("adaptive-selected")
    if baseline_rank is not None and adaptive_rank is None:
        reason_codes.append("baseline-only")
    elif baseline_rank is None and adaptive_rank is not None:
        reason_codes.append("adaptive-only")
    elif baseline_rank is None and adaptive_rank is None:
        reason_codes.append("not-selected")
    reason_codes = list(dict.fromkeys(reason_codes))
    confidence_order = {"insufficient": 0, "low": 1, "moderate": 2, "high": 3}
    confidence = adjustment.duration_forecast.confidence
    if confidence_order[adjustment.capacity_fit.confidence] > confidence_order[confidence]:
        confidence = adjustment.capacity_fit.confidence
    ignored: list[str] = []
    for dimension in adjustment.capacity_fit.dimensions:
        if dimension.status != "used":
            ignored.append(f"{dimension.name}:{dimension.status}")
    ignored.extend(adjustment.duration_forecast.ignored_reasons)
    evidence = set(adjustment.duration_forecast.evidence_event_ids)
    for dimension in adjustment.capacity_fit.dimensions:
        evidence.update(dimension.evidence_event_ids)
    selected_state = "selected" if adaptive_rank is not None else "not selected"
    concise = (
        f"{action.title} is {selected_state} in the adaptive menu. "
        f"Declared {action.duration} minutes; effective {adjustment.effective_minutes} minutes; "
        f"confidence {confidence}."
    )
    expanded = tuple(_REASON_TEXT[code] for code in reason_codes if code in _REASON_TEXT)
    counterfactuals: list[PlannerCounterfactual] = []
    available = result.returned.get("available_minutes")
    if adaptive_rank is None:
        counterfactuals.append(PlannerCounterfactual("available-time", "Available minutes needed for this task alone", adjustment.effective_minutes))
    if isinstance(available, int) and adjustment.effective_minutes > available:
        counterfactuals.append(PlannerCounterfactual("time-shortfall", "Additional minutes required", adjustment.effective_minutes - available))
    energy = result.returned.get("energy")
    levels = {"low": 1, "medium": 2, "high": 3}
    if isinstance(energy, str) and levels.get(action.energy, 0) > levels.get(energy, 0):
        counterfactuals.append(PlannerCounterfactual("energy", "Minimum energy", action.energy))
    if action.mode:
        counterfactuals.append(PlannerCounterfactual("mode", "Compatible mode", action.mode))
    if adjustment.duration_forecast.confidence == "insufficient":
        counterfactuals.append(PlannerCounterfactual("evidence", "More comparable explicit outcomes needed", None))
    return PlannerExplanation(
        EXPLANATION_SCHEMA_VERSION,
        result.policy_version,
        task_id,
        baseline_rank is not None,
        adaptive_rank is not None,
        baseline_rank,
        adaptive_rank,
        action.duration,
        adjustment.duration_forecast.calibrated_minutes,
        adjustment.effective_minutes,
        confidence,
        tuple(reason_codes),
        tuple(sorted(set(ignored))),
        tuple(sorted(evidence)),
        concise,
        expanded,
        tuple(counterfactuals),
        "Evidence references identify execution events only; unrelated journal prose is not included.",
    )
