"""Bounded adaptive policy layered over the baseline daily planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Iterable

from lifeos.feedback.avoidance import diagnose_repeated_avoidance
from lifeos.feedback.capacity import summarize_capacity_fit
from lifeos.feedback.duration import calibrate_duration
from lifeos.feedback.models import (
    AdaptiveAdjustment,
    AdaptiveMenuDelta,
    AdaptiveMode,
    AdaptivePlanResult,
    FeedbackObservation,
)
from lifeos.planning import DailyMenu, PlanningAction, build_daily_menu

ADAPTIVE_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class AdaptivePolicyConfig:
    schema_version: int = 1
    maximum_duration_multiplier: float = 2.0
    minimum_duration_multiplier: float = 0.5
    capacity_buffer_strength: float = 0.4
    avoidance_buffer: float = 0.1


def _effective_action(
    action: PlanningAction,
    *,
    observations: tuple[FeedbackObservation, ...],
    as_of: date,
    energy: str,
    motivation: str,
    time_window: str | None,
    disabled_dimensions: tuple[str, ...],
    diagnoses_by_task: dict[str, tuple[str, ...]],
    config: AdaptivePolicyConfig,
) -> tuple[PlanningAction, AdaptiveAdjustment]:
    forecast = calibrate_duration(
        observations=observations,
        task_id=action.task_id,
        declared_minutes=action.duration,
        task_shape="unspecified",
        plan_id=action.plan,
        mode=action.mode,
        as_of=as_of,
        enabled="duration" not in disabled_dimensions,
    )
    fit = summarize_capacity_fit(
        observations=observations,
        task_id=action.task_id,
        current_energy=energy,
        current_motivation=motivation,
        mode=action.mode,
        declared_minutes=action.duration,
        time_window=time_window,
        blocked=bool(action.blocked_by),
        as_of=as_of,
        disabled_dimensions=disabled_dimensions,
    )
    base = forecast.calibrated_minutes if forecast.confidence != "insufficient" else action.duration
    reason_codes: list[str] = []
    if base != action.duration:
        reason_codes.append("duration-calibrated")
    fit_multiplier = 1.0
    if fit.confidence != "insufficient" and fit.total_adjustment:
        fit_multiplier = 1.0 - fit.total_adjustment * config.capacity_buffer_strength
        reason_codes.append("capacity-fit-buffer")
    diagnosis_ids = diagnoses_by_task.get(action.task_id, ())
    diagnosis_multiplier = 1.0 + (config.avoidance_buffer if diagnosis_ids else 0.0)
    if diagnosis_ids:
        reason_codes.append("avoidance-uncertainty-buffer")
    raw = int(round(base * fit_multiplier * diagnosis_multiplier))
    lower = max(1, int(round(action.duration * config.minimum_duration_multiplier)))
    upper = min(1440, int(round(action.duration * config.maximum_duration_multiplier)))
    effective = max(lower, min(upper, raw))
    capped = effective != raw
    if capped:
        reason_codes.append("duration-cap-applied")
    transformed = replace(action, duration=effective)
    return transformed, AdaptiveAdjustment(
        action.task_id,
        action.duration,
        effective,
        forecast,
        fit,
        diagnosis_ids,
        capped,
        tuple(reason_codes),
    )


def _decorate_menu(menu: DailyMenu, adjustments: dict[str, AdaptiveAdjustment]) -> DailyMenu:
    items = tuple(
        replace(
            item,
            reason=item.reason
            + (
                "; adaptive evidence: " + ", ".join(adjustments[item.task_id].reason_codes)
                if adjustments[item.task_id].reason_codes
                else "; no usable adaptive evidence"
            ),
        )
        for item in menu.items
    )
    return replace(menu, items=items)


def build_adaptive_menu(
    *,
    actions: tuple[PlanningAction, ...],
    observations: Iterable[FeedbackObservation],
    as_of: date,
    available_minutes: int,
    energy: str,
    motivation: str,
    mode_filter: str | None = None,
    adaptive_mode: AdaptiveMode = "off",
    time_window: str | None = None,
    disabled_dimensions: tuple[str, ...] = (),
    dismissed_diagnosis_fingerprints: tuple[str, ...] = (),
    config: AdaptivePolicyConfig | None = None,
) -> AdaptivePlanResult:
    if adaptive_mode not in {"off", "shadow", "active"}:
        raise ValueError("adaptive_mode must be off, shadow, or active")
    cfg = config or AdaptivePolicyConfig()
    baseline = build_daily_menu(
        actions=actions,
        as_of=as_of,
        available_minutes=available_minutes,
        energy=energy,
        motivation=motivation,
        mode=mode_filter,
    )
    items = tuple(sorted(observations, key=lambda item: (item.day, item.event_id)))
    diagnoses = diagnose_repeated_avoidance(
        observations=items, as_of=as_of, dismissed_fingerprints=dismissed_diagnosis_fingerprints
    )
    diagnoses_by_task: dict[str, tuple[str, ...]] = {}
    for diagnosis in diagnoses:
        if not diagnosis.dismissed and diagnosis.confidence != "insufficient":
            diagnoses_by_task.setdefault(diagnosis.task_id, tuple())
            diagnoses_by_task[diagnosis.task_id] = (
                *diagnoses_by_task[diagnosis.task_id],
                diagnosis.diagnosis_id,
            )
    transformed: list[PlanningAction] = []
    adjustments: list[AdaptiveAdjustment] = []
    for action in sorted(actions, key=lambda item: item.task_id):
        effective, adjustment = _effective_action(
            action,
            observations=items,
            as_of=as_of,
            energy=energy,
            motivation=motivation,
            time_window=time_window,
            disabled_dimensions=disabled_dimensions,
            diagnoses_by_task=diagnoses_by_task,
            config=cfg,
        )
        transformed.append(effective)
        adjustments.append(adjustment)
    raw_adaptive = build_daily_menu(
        actions=tuple(transformed),
        as_of=as_of,
        available_minutes=available_minutes,
        energy=energy,
        motivation=motivation,
        mode=mode_filter,
    )
    adaptive = (
        _decorate_menu(raw_adaptive, {item.task_id: item for item in adjustments})
        if any(item.reason_codes for item in adjustments)
        else baseline
    )
    baseline_ids = {item.task_id for item in baseline.items}
    adaptive_ids = {item.task_id for item in adaptive.items}
    deltas = tuple(
        AdaptiveMenuDelta(
            item.task_id,
            item.task_id in baseline_ids,
            item.task_id in adaptive_ids,
            item.declared_minutes,
            item.effective_minutes,
            item.reason_codes,
        )
        for item in adjustments
        if item.task_id in baseline_ids
        or item.task_id in adaptive_ids
        or item.declared_minutes != item.effective_minutes
    )
    has_diagnostics = False
    has_evidence = any(item.reason_codes for item in adjustments)
    status = "diagnostic" if has_diagnostics else "available" if has_evidence else "insufficient"
    returned = baseline if adaptive_mode in {"off", "shadow"} else adaptive
    if adaptive_mode == "off":
        adaptive = baseline
        deltas = tuple(
            replace(
                delta,
                adaptive_selected=delta.baseline_selected,
                effective_minutes=delta.declared_minutes,
                reason_codes=(),
            )
            for delta in deltas
        )
    return AdaptivePlanResult(
        1,
        ADAPTIVE_POLICY_VERSION,
        adaptive_mode,
        asdict(baseline),
        asdict(adaptive),
        asdict(returned),
        tuple(adjustments),
        deltas,
        status,  # type: ignore[arg-type]
    )
