"""Weekly-review summaries derived from execution feedback."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lifeos.feedback.avoidance import diagnose_repeated_avoidance
from lifeos.feedback.dataset import build_evidence_dataset
from lifeos.feedback.duration import calibrate_duration
from lifeos.planning import load_plan_actions


@dataclass(frozen=True, slots=True)
class FeedbackReviewSuggestion:
    suggestion_id: str
    kind: str
    title: str
    detail: str
    target_path: str
    task_id: str | None
    confidence: str
    evidence_fingerprint: str
    evidence_event_ids: tuple[str, ...]
    proposed_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"feedback-review:{digest}"


def build_feedback_review_summary(
    *,
    vault_root: Path,
    as_of: date,
) -> tuple[FeedbackReviewSuggestion, ...]:
    """Return deterministic, advisory weekly-review suggestions.

    The function is read-only. It deliberately emits proposals-to-consider rather
    than changing plans or interpreting missing outcomes as failure.
    """

    dataset = build_evidence_dataset(vault_root, as_of=as_of)
    actions = load_plan_actions(vault_root)
    suggestions: list[FeedbackReviewSuggestion] = []

    for action in actions:
        forecast = calibrate_duration(
            observations=dataset.observations,
            task_id=action.task_id,
            declared_minutes=action.duration,
            plan_id=action.plan,
            mode=action.mode,
            as_of=as_of,
        )
        if forecast.confidence not in {"moderate", "high"}:
            continue
        if forecast.direction not in {"underestimated", "overestimated"}:
            continue
        fingerprint = hashlib.sha256(
            "\0".join(("duration", action.task_id, *forecast.evidence_event_ids)).encode("utf-8")
        ).hexdigest()
        suggestions.append(
            FeedbackReviewSuggestion(
                _stable_id("duration", action.task_id),
                "systematic_duration_error",
                f"Review the estimate for {action.title}",
                (
                    f"Recent explicit outcomes suggest {action.duration} minutes may be "
                    f"{forecast.direction}; the cautious calibrated estimate is "
                    f"{forecast.calibrated_minutes} minutes."
                ),
                action.source_path,
                action.task_id,
                forecast.confidence,
                fingerprint,
                forecast.evidence_event_ids,
                "update_task_estimate",
            )
        )

    diagnoses = diagnose_repeated_avoidance(
        observations=dataset.observations,
        as_of=as_of,
    )
    action_by_task = {action.task_id: action for action in actions}
    proposal_kind = {
        "underspecified": "clarify_task",
        "oversized": "decompose_task",
        "blocked": "add_blocker",
        "estimate_error": "update_task_estimate",
        "capacity_mismatch": "change_task_fit",
        "motivation_mismatch": "change_task_fit",
        "unaccounted": "reduce_tracking",
        "stalled": "open_goal_review",
    }
    for diagnosis in diagnoses:
        if diagnosis.dismissed:
            continue
        matched_action = action_by_task.get(diagnosis.task_id)
        target_path = matched_action.source_path if matched_action is not None else ""
        suggestions.append(
            FeedbackReviewSuggestion(
                _stable_id("avoidance", diagnosis.diagnosis_id),
                diagnosis.kind,
                diagnosis.title,
                diagnosis.hypothesis,
                target_path,
                diagnosis.task_id,
                diagnosis.confidence,
                diagnosis.evidence_fingerprint,
                diagnosis.evidence_event_ids,
                proposal_kind[diagnosis.kind],
            )
        )

    active_by_source: dict[str, list[Any]] = {}
    for action in actions:
        active_by_source.setdefault(action.source_path, []).append(action)
    for source_path, plan_actions in sorted(active_by_source.items()):
        active = [item for item in plan_actions if item.status in {"todo", "active", "pending"}]
        if active and not any(not item.blocked_by for item in active):
            evidence = tuple(sorted(item.task_id for item in active))
            fingerprint = hashlib.sha256(
                "\0".join(("no-eligible-action", source_path, *evidence)).encode("utf-8")
            ).hexdigest()
            suggestions.append(
                FeedbackReviewSuggestion(
                    _stable_id("no-eligible-action", source_path),
                    "no_eligible_next_action",
                    "This plan has no unblocked next action",
                    "Every active task currently has a blocker. Review dependencies or pause the plan.",
                    source_path,
                    None,
                    "moderate",
                    fingerprint,
                    evidence,
                    "open_goal_review",
                )
            )

    return tuple(
        sorted(suggestions, key=lambda item: (item.kind, item.target_path, item.task_id or ""))
    )
