"""Tentative, noncausal capacity-fit summaries."""

from __future__ import annotations

from datetime import date
from typing import Iterable

from lifeos.feedback.models import CapacityDimension, CapacityFitSummary, FeedbackObservation

CAPACITY_POLICY_VERSION = 1
_LEVELS = {"low": 1, "medium": 2, "high": 3}
_DIMENSIONS = ("energy", "motivation", "mode", "duration_band", "time_window", "blocker")


def _score(item: FeedbackObservation) -> float | None:
    if item.excluded or item.outcome in {"cancelled", "unaccounted", "started"}:
        return None
    if item.outcome == "done":
        return 1.0
    if item.outcome == "partial":
        return item.completion_fraction if item.completion_fraction is not None else 0.5
    if item.outcome in {"skipped", "deferred"}:
        return 0.0
    return None


def _band(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    if minutes <= 20:
        return "short"
    if minutes <= 60:
        return "medium"
    return "long"


def _time_window(item: FeedbackObservation) -> str | None:
    if not item.started_at:
        return None
    try:
        hour = int(item.started_at[11:13])
    except (ValueError, IndexError):
        return None
    return "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


def _confidence(count: int, effect: float, *, minimum: int) -> str:
    if count < minimum:
        return "insufficient"
    if count >= minimum * 2 and abs(effect) >= 0.15:
        return "high"
    if count >= minimum + 2:
        return "moderate"
    return "low"


def _dimension(
    *,
    name: str,
    observations: tuple[FeedbackObservation, ...],
    baseline: float,
    current_value: object,
    disabled: set[str],
    minimum: int,
    as_of: date,
    stale_after_days: int,
) -> CapacityDimension:
    if name in disabled:
        return CapacityDimension(
            name,
            "disabled",
            0,
            0,
            None,
            baseline,
            0.0,
            "unknown",
            "insufficient",
            (),
            f"{name} feedback is disabled.",
        )  # type: ignore[arg-type]
    if current_value is None or current_value == "":
        return CapacityDimension(
            name,
            "missing",
            0,
            len(observations),
            None,
            baseline,
            0.0,
            "unknown",
            "insufficient",
            (),
            f"No current {name} value was supplied.",
        )  # type: ignore[arg-type]
    usable: list[tuple[FeedbackObservation, float]] = []
    missing = 0
    for item in observations:
        if (as_of - item.day).days > stale_after_days or item.day > as_of:
            continue
        score = _score(item)
        if score is None:
            continue
        value: object
        if name == "energy":
            value = item.energy_before
        elif name == "motivation":
            value = item.motivation_before
        elif name == "mode":
            value = item.mode
        elif name == "duration_band":
            value = _band(item.planned_minutes)
        elif name == "time_window":
            value = _time_window(item)
        else:
            value = item.blocked
        if value is None or value == "unspecified":
            missing += 1
        elif value == current_value:
            usable.append((item, score))
    if len(usable) < minimum:
        return CapacityDimension(
            name,
            "insufficient",
            len(usable),
            missing,
            None,
            baseline,
            0.0,
            "unknown",
            "insufficient",
            tuple(sorted(item.event_id for item, _ in usable)),
            f"Only {len(usable)} comparable {name} observations are available; no adjustment is applied.",
        )  # type: ignore[arg-type]
    rate = sum(score for _, score in usable) / len(usable)
    raw_effect = rate - baseline
    contradictory = 0.35 < rate < 0.65 and len(usable) >= minimum * 2
    if contradictory:
        return CapacityDimension(
            name,
            "contradictory",
            len(usable),
            missing,
            round(rate, 4),
            round(baseline, 4),
            0.0,
            "neutral",
            "low",
            tuple(sorted(item.event_id for item, _ in usable)),
            f"Comparable {name} outcomes are mixed; this association is not used.",
        )  # type: ignore[arg-type]
    adjustment = max(-0.15, min(0.15, raw_effect * 0.3))
    direction = (
        "better_fit" if adjustment >= 0.03 else "worse_fit" if adjustment <= -0.03 else "neutral"
    )
    confidence = _confidence(len(usable), raw_effect, minimum=minimum)
    return CapacityDimension(
        name,
        "used",
        len(usable),
        missing,
        round(rate, 4),
        round(baseline, 4),
        round(adjustment, 4),
        direction,
        confidence,
        tuple(sorted(item.event_id for item, _ in usable)),
        f"Recorded {name} is associated with a {direction.replace('_', ' ')} in this history; this is tentative and noncausal.",
    )  # type: ignore[arg-type]


def summarize_capacity_fit(
    *,
    observations: Iterable[FeedbackObservation],
    task_id: str,
    current_energy: str | None,
    current_motivation: str | None,
    mode: str | None,
    declared_minutes: int | None,
    time_window: str | None = None,
    blocked: bool | None = False,
    as_of: date,
    disabled_dimensions: tuple[str, ...] = (),
    minimum_samples: int = 4,
    stale_after_days: int = 180,
) -> CapacityFitSummary:
    items = tuple(sorted(observations, key=lambda item: (item.day, item.event_id)))
    scored = [
        score
        for item in items
        if (score := _score(item)) is not None
        and item.day <= as_of
        and (as_of - item.day).days <= stale_after_days
    ]
    baseline = sum(scored) / len(scored) if scored else 0.5
    values: dict[str, object] = {
        "energy": current_energy,
        "motivation": current_motivation,
        "mode": mode.casefold() if isinstance(mode, str) else None,
        "duration_band": _band(declared_minutes),
        "time_window": time_window,
        "blocker": blocked,
    }
    disabled = set(disabled_dimensions)
    dimensions = tuple(
        _dimension(
            name=name,
            observations=items,
            baseline=baseline,
            current_value=values[name],
            disabled=disabled,
            minimum=minimum_samples,
            as_of=as_of,
            stale_after_days=stale_after_days,
        )
        for name in _DIMENSIONS
    )
    used = [item for item in dimensions if item.status == "used"]
    total = max(-0.25, min(0.25, sum(item.adjustment for item in used)))
    confidence = "insufficient"
    if used:
        ranks = {"insufficient": 0, "low": 1, "moderate": 2, "high": 3}
        confidence = min((item.confidence for item in used), key=lambda value: ranks[value])
    return CapacityFitSummary(
        CAPACITY_POLICY_VERSION,
        task_id,
        round(total, 4),
        confidence,  # type: ignore[arg-type]
        dimensions,
        tuple(sorted(disabled)),
        "These are tentative associations from explicit outcomes. They do not establish causation, health effects, discipline, or personal worth.",
    )
