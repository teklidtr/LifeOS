"""Cautious deterministic duration calibration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Iterable

from lifeos.feedback.models import DurationForecast, FeedbackObservation

DURATION_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class DurationCalibrationConfig:
    task_min_samples: int = 3
    task_shape_min_samples: int = 4
    plan_min_samples: int = 5
    mode_min_samples: int = 6
    global_min_samples: int = 8
    stale_after_days: int = 180
    minimum_multiplier: float = 0.5
    maximum_multiplier: float = 2.0


@dataclass(frozen=True, slots=True)
class _Sample:
    observation: FeedbackObservation
    ratio: float


def _usable_samples(observations: Iterable[FeedbackObservation], *, as_of: date, stale_after_days: int) -> tuple[list[_Sample], list[str]]:
    samples: list[_Sample] = []
    ignored: list[str] = []
    for item in observations:
        if item.excluded:
            ignored.append(f"{item.event_id}:excluded")
            continue
        age = (as_of - item.day).days
        if age < 0:
            ignored.append(f"{item.event_id}:future")
            continue
        if age > stale_after_days:
            ignored.append(f"{item.event_id}:stale")
            continue
        if item.outcome not in {"done", "partial"}:
            ignored.append(f"{item.event_id}:outcome-{item.outcome}")
            continue
        if not item.planned_minutes or not item.actual_minutes:
            ignored.append(f"{item.event_id}:missing-duration")
            continue
        actual = float(item.actual_minutes)
        if item.outcome == "partial":
            fraction = item.completion_fraction
            if fraction is None or fraction <= 0.0:
                ignored.append(f"{item.event_id}:partial-without-progress")
                continue
            actual = actual / fraction
        ratio = actual / item.planned_minutes
        if ratio <= 0 or ratio > 10:
            ignored.append(f"{item.event_id}:extreme-ratio")
            continue
        samples.append(_Sample(item, ratio))
    return samples, ignored


def _matching_levels(
    samples: list[_Sample],
    *,
    task_id: str,
    task_shape: str,
    plan_id: str,
    mode: str,
    config: DurationCalibrationConfig,
) -> tuple[tuple[str, str, int, list[_Sample]], ...]:
    return (
        ("task", task_id, config.task_min_samples, [s for s in samples if s.observation.task_id == task_id]),
        ("task_shape", task_shape, config.task_shape_min_samples, [s for s in samples if task_shape and task_shape != "unspecified" and s.observation.task_shape == task_shape]),
        ("plan", plan_id, config.plan_min_samples, [s for s in samples if plan_id and s.observation.plan_id == plan_id]),
        ("mode", mode, config.mode_min_samples, [s for s in samples if mode and mode != "unspecified" and s.observation.mode == mode]),
        ("global", "all", config.global_min_samples, list(samples)),
    )


def _trim_outliers(samples: list[_Sample]) -> tuple[list[_Sample], int, float, float]:
    ratios = [sample.ratio for sample in samples]
    center = float(median(ratios))
    deviations = [abs(value - center) for value in ratios]
    mad = float(median(deviations))
    tolerance = max(0.5, 3.0 * mad)
    kept = [sample for sample in samples if abs(sample.ratio - center) <= tolerance]
    if not kept:
        return samples, 0, center, mad
    return kept, len(samples) - len(kept), float(median([s.ratio for s in kept])), mad


def _confidence(sample_count: int, threshold: int, spread: float, freshest_age: int) -> str:
    if sample_count < threshold:
        return "insufficient"
    if sample_count >= threshold * 2 and spread <= 0.25 and freshest_age <= 30:
        return "high"
    if sample_count >= threshold + 2 and freshest_age <= 90:
        return "moderate"
    return "low"


def calibrate_duration(
    *,
    observations: Iterable[FeedbackObservation],
    task_id: str,
    declared_minutes: int,
    task_shape: str = "unspecified",
    plan_id: str = "",
    mode: str = "unspecified",
    as_of: date,
    enabled: bool = True,
    config: DurationCalibrationConfig | None = None,
) -> DurationForecast:
    if type(declared_minutes) is not int or declared_minutes <= 0 or declared_minutes > 1440:
        raise ValueError("declared_minutes must be from 1 to 1440")
    cfg = config or DurationCalibrationConfig()
    if not enabled:
        return DurationForecast(DURATION_POLICY_VERSION, task_id, declared_minutes, declared_minutes, "none", "", 0, 0, None, None, None, "insufficient", "unknown", (), ("calibration-disabled",), False)
    usable, ignored = _usable_samples(observations, as_of=as_of, stale_after_days=cfg.stale_after_days)
    chosen: tuple[str, str, int, list[_Sample]] | None = None
    for level in _matching_levels(usable, task_id=task_id, task_shape=task_shape, plan_id=plan_id, mode=mode, config=cfg):
        if len(level[3]) >= level[2]:
            chosen = level
            break
    if chosen is None:
        return DurationForecast(DURATION_POLICY_VERSION, task_id, declared_minutes, declared_minutes, "none", "", 0, 0, None, None, max((s.observation.day for s in usable), default=None), "insufficient", "unknown", (), tuple(sorted(ignored)), True)
    level, key, threshold, level_samples = chosen
    kept, excluded_outliers, center, spread = _trim_outliers(level_samples)
    if len(kept) < threshold:
        return DurationForecast(DURATION_POLICY_VERSION, task_id, declared_minutes, declared_minutes, "none", "", len(kept), excluded_outliers, center, spread, max((s.observation.day for s in kept), default=None), "insufficient", "unknown", tuple(sorted(s.observation.event_id for s in kept)), tuple(sorted(ignored + ["outliers-below-threshold"])), True)
    shrink = min(1.0, len(kept) / (threshold * 2.0))
    multiplier = 1.0 + (center - 1.0) * shrink
    multiplier = min(cfg.maximum_multiplier, max(cfg.minimum_multiplier, multiplier))
    calibrated = max(1, min(1440, int(round(declared_minutes * multiplier))))
    freshest = max(s.observation.day for s in kept)
    confidence = _confidence(len(kept), threshold, spread, (as_of - freshest).days)
    delta_ratio = calibrated / declared_minutes
    direction = "underestimated" if delta_ratio >= 1.1 else "overestimated" if delta_ratio <= 0.9 else "aligned"
    return DurationForecast(
        DURATION_POLICY_VERSION,
        task_id,
        declared_minutes,
        calibrated,
        level,  # type: ignore[arg-type]
        key,
        len(kept),
        excluded_outliers,
        round(center, 4),
        round(spread, 4),
        freshest,
        confidence,  # type: ignore[arg-type]
        direction,
        tuple(sorted(s.observation.event_id for s in kept)),
        tuple(sorted(ignored)),
        True,
    )
