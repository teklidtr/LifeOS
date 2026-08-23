"""Durable progress, answers, and lifecycle transitions for review artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from lifeos.daily.errors import DailyInteractionError
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.contracts import (
    ReviewAnswer,
    ReviewArtifact,
    ReviewLifecycleEvent,
    ReviewPhaseProgress,
    phase_ids_for_kind,
)
from lifeos.vault import VaultAccessError, iter_vault_markdown

SectionProgressAction = Literal["complete", "skip", "reopen"]
PhaseProgressAction = Literal["complete", "skip", "reopen"]


def _event(
    review_id: str, transition: str, now: datetime, actor_id: str, note: str | None = None
) -> ReviewLifecycleEvent:
    stamp = now.isoformat()
    digest = hashlib.sha256(
        f"{review_id}\0{transition}\0{stamp}\0{actor_id}\0{note or ''}".encode()
    ).hexdigest()[:24]
    return ReviewLifecycleEvent(f"reviewevent:{digest}", transition, stamp, actor_id, note)


def _phase(metadata: ReviewArtifact, phase_id: str) -> tuple[int, ReviewPhaseProgress]:
    for index, phase in enumerate(metadata.metadata.phases):
        if phase.phase_id == phase_id:
            return index, phase
    raise DailyInteractionError(
        "invalid_review_phase",
        f"Phase {phase_id} is not part of {metadata.metadata.review_id}.",
        "Choose a phase shown in the review artifact.",
    )


class ReviewProgressService:
    def __init__(self, artifact_service: ReviewArtifactService) -> None:
        self.artifacts = artifact_service

    def update_section(
        self,
        *,
        review_id: str,
        phase_id: str,
        section_id: str,
        action: SectionProgressAction,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        index, phase = _phase(artifact, phase_id)
        completed = set(phase.completed_sections)
        skipped = set(phase.skipped_sections)
        if action == "complete":
            completed.add(section_id)
            skipped.discard(section_id)
        elif action == "skip":
            skipped.add(section_id)
            completed.discard(section_id)
        elif action == "reopen":
            completed.discard(section_id)
            skipped.discard(section_id)
        else:
            raise DailyInteractionError(
                "invalid_progress_action",
                f"Unsupported action: {action}",
                "Choose complete, skip, or reopen.",
            )
        updated_phase = replace(
            phase,
            state="pending" if action == "reopen" else phase.state,
            completed_sections=tuple(sorted(completed)),
            skipped_sections=tuple(sorted(skipped)),
            current_section=section_id,
            completed_at=None if action == "reopen" else phase.completed_at,
        )
        phases = list(artifact.metadata.phases)
        phases[index] = updated_phase
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(phases=tuple(phases), current_phase=phase_id),
        )

    def update_phase(
        self,
        *,
        review_id: str,
        phase_id: str,
        action: PhaseProgressAction,
        required_sections: tuple[str, ...],
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        index, phase = _phase(artifact, phase_id)
        if action == "complete":
            accounted = set(phase.completed_sections) | set(phase.skipped_sections)
            missing = sorted(set(required_sections) - accounted)
            if missing:
                raise DailyInteractionError(
                    "review_phase_incomplete",
                    f"Required sections are not reviewed: {', '.join(missing)}",
                    "Complete or intentionally skip each required section.",
                    {"missing_sections": missing},
                )
            updated_phase = replace(
                phase, state="completed", completed_at=now.isoformat(), current_section=None
            )
        elif action == "skip":
            updated_phase = replace(
                phase, state="skipped", completed_at=now.isoformat(), current_section=None
            )
        elif action == "reopen":
            updated_phase = replace(phase, state="pending", completed_at=None)
        else:
            raise DailyInteractionError(
                "invalid_progress_action",
                f"Unsupported action: {action}",
                "Choose complete, skip, or reopen.",
            )
        phases = list(artifact.metadata.phases)
        phases[index] = updated_phase
        events = (
            *artifact.metadata.lifecycle_events,
            _event(review_id, f"phase_{action}:{phase_id}", now, self.artifacts.actor_id),
        )
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(
                phases=tuple(phases), current_phase=phase_id, lifecycle_events=events
            ),
        )

    def answer(
        self,
        *,
        review_id: str,
        prompt_id: str,
        value: str,
        phase_id: str | None,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ReviewArtifact:
        if not value.strip():
            raise DailyInteractionError(
                "empty_review_answer",
                "Review answer must not be blank.",
                "Write an answer or leave the prompt unanswered.",
            )
        artifact = self.artifacts.load_id(review_id)
        if phase_id is not None and phase_id not in phase_ids_for_kind(
            artifact.metadata.review_kind
        ):
            raise DailyInteractionError(
                "invalid_review_phase",
                f"Phase {phase_id} is invalid.",
                "Choose a phase from this artifact.",
            )
        replacement = ReviewAnswer(prompt_id, value.strip(), now.isoformat(), phase_id)
        answers = [
            answer
            for answer in artifact.metadata.answers
            if (answer.prompt_id, answer.phase_id) != (prompt_id, phase_id)
        ]
        answers.append(replacement)
        answers.sort(key=lambda answer: (answer.phase_id or "", answer.prompt_id))
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(answers=tuple(answers), current_phase=phase_id),
        )

    def complete_review(
        self,
        *,
        review_id: str,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        pending = [phase.phase_id for phase in artifact.metadata.phases if phase.state == "pending"]
        if pending:
            raise DailyInteractionError(
                "review_incomplete",
                f"Review phases are still pending: {', '.join(pending)}",
                "Complete or intentionally skip each phase before closing the review.",
                {"pending_phases": pending},
            )
        events = (
            *artifact.metadata.lifecycle_events,
            _event(review_id, "completed", now, self.artifacts.actor_id),
        )
        summary = "## Completion summary\n\nReview completed. " + ", ".join(
            f"{phase.phase_id}: {phase.state}" for phase in artifact.metadata.phases
        )
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(
                status="completed",
                lifecycle_events=events,
                managed_blocks={"completion-summary": summary},
            ),
        )

    def skip_review(
        self,
        *,
        review_id: str,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
        note: str | None = None,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        phases = tuple(
            replace(phase, state="skipped", completed_at=now.isoformat())
            if phase.state == "pending"
            else phase
            for phase in artifact.metadata.phases
        )
        events = (
            *artifact.metadata.lifecycle_events,
            _event(review_id, "skipped", now, self.artifacts.actor_id, note),
        )
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(
                status="skipped",
                phases=phases,
                lifecycle_events=events,
                managed_blocks={
                    "completion-summary": "## Completion summary\n\nReview was intentionally skipped."
                },
            ),
        )

    def reopen_review(
        self,
        *,
        review_id: str,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
    ) -> ReviewArtifact:
        artifact = self.artifacts.load_id(review_id)
        events = (
            *artifact.metadata.lifecycle_events,
            _event(review_id, "reopened", now, self.artifacts.actor_id),
        )
        return self.artifacts.update(
            review_id=review_id,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            update=ReviewArtifactUpdate(
                status="open",
                lifecycle_events=events,
                managed_blocks={"completion-summary": "## Completion summary\n\nReview is open."},
            ),
        )


def rebuild_progress_cache(*, vault_root: Path, runtime_dir: Path) -> dict[str, dict[str, object]]:
    """Rebuild disposable progress summaries from canonical Markdown artifacts."""
    service = ReviewArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    rows: dict[str, dict[str, object]] = {}
    try:
        sources = tuple(
            source
            for source in iter_vault_markdown(vault_root, roots=("reviews",))
            if source.relative_path.startswith(("reviews/daily/", "reviews/weekly/"))
        )
    except VaultAccessError as exc:
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check vault access and retry."
        ) from exc
    for source in sources:
        try:
            artifact = service.load_path(source.relative_path)
        except DailyInteractionError:
            continue
        rows[artifact.metadata.review_id] = {
            "path": artifact.path,
            "content_hash": artifact.content_hash,
            "status": artifact.metadata.status,
            "current_phase": artifact.metadata.current_phase,
            "phases": [asdict(phase) for phase in artifact.metadata.phases],
            "updated_at": artifact.metadata.updated_at,
        }
    target = runtime_dir / "reviews" / "progress-index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(rows, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return rows
