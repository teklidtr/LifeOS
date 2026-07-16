"""Deterministic repeated-avoidance hypotheses."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date
from typing import Iterable

from lifeos.feedback.models import AvoidanceDiagnosis, FeedbackObservation

AVOIDANCE_POLICY_VERSION = 1
_ADVERSE = frozenset({"skipped", "deferred", "partial", "unaccounted"})


def _hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _kind(items: tuple[FeedbackObservation, ...]) -> tuple[str, tuple[str, ...]]:
    reasons = " ".join((item.reason or "").casefold() for item in items)
    if any(word in reasons for word in ("unclear", "vague", "underspecified", "don't know where", "not defined")):
        return "underspecified", ("clarify", "decompose", "ask_later")
    if any(word in reasons for word in ("too big", "too long", "no time", "oversized", "larger than")):
        return "oversized", ("decompose", "reduce_duration", "ask_later")
    if any(word in reasons for word in ("blocked", "waiting", "dependency")) or sum(item.blocked is True for item in items) >= 2:
        return "blocked", ("add_blocker", "review_blocker", "pause")
    ratios = [item.actual_minutes / item.planned_minutes for item in items if item.actual_minutes and item.planned_minutes and item.outcome in {"done", "partial"}]
    if len(ratios) >= 2 and sum(ratio >= 1.3 for ratio in ratios) >= 2:
        return "estimate_error", ("review_estimate", "decompose")
    if sum(item.energy_before == "high" and item.motivation_before == "low" for item in items) >= 2:
        return "motivation_mismatch", ("change_mode", "reduce_duration", "review_goal")
    if sum(item.energy_before == "low" for item in items) >= 2:
        return "capacity_mismatch", ("change_mode", "reduce_duration", "choose_capacity_window")
    if sum(item.outcome == "unaccounted" for item in items) >= 2:
        return "unaccounted", ("reconcile", "reduce_tracking", "ask_later")
    return "stalled", ("clarify", "decompose", "review_goal", "pause")


def diagnose_repeated_avoidance(
    *,
    observations: Iterable[FeedbackObservation],
    as_of: date,
    minimum_repetitions: int = 3,
    recency_days: int = 60,
    dismissed_fingerprints: tuple[str, ...] = (),
) -> tuple[AvoidanceDiagnosis, ...]:
    grouped: dict[tuple[str, str], list[FeedbackObservation]] = {}
    for item in observations:
        if item.excluded or item.day > as_of or (as_of - item.day).days > recency_days:
            continue
        grouped.setdefault((item.plan_id, item.task_id), []).append(item)
    dismissed = set(dismissed_fingerprints)
    diagnoses: list[AvoidanceDiagnosis] = []
    for (plan_id, task_id), raw_items in sorted(grouped.items()):
        items = tuple(sorted(raw_items, key=lambda item: (item.day, item.event_id)))
        adverse = tuple(item for item in items if item.outcome in _ADVERSE)
        successes = sum(item.outcome == "done" for item in items)
        if len(adverse) < minimum_repetitions:
            continue
        if successes >= len(adverse) or successes / len(items) >= 0.5:
            continue
        kind, actions = _kind(adverse)
        evidence_ids = tuple(item.event_id for item in adverse)
        fingerprint = _hash(plan_id, task_id, kind, *evidence_ids)
        diagnosis_id = "avoidance-" + _hash(plan_id, task_id, kind)[:16]
        counts = Counter(item.outcome for item in adverse)
        missing: list[str] = []
        if all(item.reason is None for item in adverse):
            missing.append("No explicit skip or defer reasons were recorded.")
        if all(item.energy_before is None for item in adverse):
            missing.append("Energy before the task is unknown.")
        if all(item.motivation_before is None for item in adverse):
            missing.append("Motivation before the task is unknown.")
        confidence = "moderate" if len(adverse) >= minimum_repetitions + 2 and len({item.outcome for item in adverse}) <= 2 else "low"
        title = {
            "underspecified": "The next action may be underspecified",
            "oversized": "The task may be larger than available windows",
            "blocked": "A recurring blocker may be unresolved",
            "estimate_error": "The task may be consistently underestimated",
            "capacity_mismatch": "The task may not fit recent energy windows",
            "motivation_mismatch": "The task may have enough energy but weak pull",
            "unaccounted": "This outcome repeatedly remains unaccounted",
            "stalled": "This task shape may be stalled",
        }[kind]
        hypothesis = (
            f"This is a tentative question based on {len(adverse)} recent outcomes "
            f"({', '.join(f'{key}={value}' for key, value in sorted(counts.items()))}). "
            "It is not a judgment about discipline, character, or health."
        )
        competing = (
            "The task may have become less important.",
            "External events or missing context may explain the pattern.",
            "The recorded task may not match the work actually performed.",
        )
        diagnoses.append(AvoidanceDiagnosis(
            AVOIDANCE_POLICY_VERSION,
            diagnosis_id,
            fingerprint,
            task_id,
            plan_id,
            kind,  # type: ignore[arg-type]
            title,
            hypothesis,
            confidence,  # type: ignore[arg-type]
            evidence_ids,
            tuple(item.day for item in adverse),
            competing,
            tuple(missing),
            actions,
            fingerprint in dismissed,
        ))
    return tuple(diagnoses)
