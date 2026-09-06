"""First-class weekly review orchestration and bounded orientation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import Any, Literal

from lifeos.reviews.artifact import ReviewArtifactService
from lifeos.reviews.contracts import ReviewArtifact, ReviewSnapshot
from lifeos.reviews.progress import ReviewProgressService
from lifeos.reviews.pattern_integration import refresh_review_snapshot


@dataclass(frozen=True, slots=True)
class WeeklyReviewPrompt:
    prompt_id: str
    label: str
    optional: bool = True


@dataclass(frozen=True, slots=True)
class WeeklyReviewDueState:
    state: Literal["available", "due", "overdue", "completed", "skipped"]
    reason: str


@dataclass(frozen=True, slots=True)
class WeeklyReviewState:
    artifact: ReviewArtifact
    snapshot: ReviewSnapshot
    prompts: tuple[WeeklyReviewPrompt, ...]
    required_sections: tuple[str, ...]
    due: WeeklyReviewDueState
    next_section: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROMPTS = (
    WeeklyReviewPrompt("weekly-story", "What changed this week?", False),
    WeeklyReviewPrompt(
        "weekly-pattern", "Which repeated pattern is supported by explicit evidence?"
    ),
    WeeklyReviewPrompt("weekly-stop", "What should stop, pause, or stay intentionally untouched?"),
    WeeklyReviewPrompt("weekly-orientation", "What direction deserves attention next week?", False),
)


def weekly_due_state(artifact: ReviewArtifact, now: datetime) -> WeeklyReviewDueState:
    phase = artifact.metadata.phases[0]
    if phase.state == "completed" or artifact.metadata.status == "completed":
        return WeeklyReviewDueState(
            "completed", "This weekly review is completed and may be reopened."
        )
    if phase.state == "skipped" or artifact.metadata.status == "skipped":
        return WeeklyReviewDueState(
            "skipped", "This weekly review was intentionally skipped and may be reopened."
        )
    if now.date() > artifact.metadata.period_end:
        return WeeklyReviewDueState(
            "overdue", "The review period has ended and the artifact remains open."
        )
    if now.date() == artifact.metadata.period_end and now.timetz().replace(tzinfo=None) >= time(
        17, 0
    ):
        return WeeklyReviewDueState("due", "The ISO week is ending and the review remains open.")
    return WeeklyReviewDueState("available", "The weekly review is available but not due.")


def _required(snapshot: ReviewSnapshot) -> tuple[str, ...]:
    return tuple(section.section_id for section in snapshot.sections if not section.optional)


def _next(snapshot: ReviewSnapshot, artifact: ReviewArtifact) -> str | None:
    phase = artifact.metadata.phases[0]
    accounted = set(phase.completed_sections) | set(phase.skipped_sections)
    for section in snapshot.sections:
        if not section.optional and section.section_id not in accounted:
            return section.section_id
    for section in snapshot.sections:
        if section.state == "ready" and section.section_id not in accounted:
            return section.section_id
    return None


def open_weekly_review(
    *,
    service: ReviewArtifactService,
    runtime_dir: Any,
    day: date,
    timezone: str,
    now: datetime,
    idempotency_key: str,
    refresh: bool = True,
) -> WeeklyReviewState:
    artifact = service.open_or_create(
        kind="weekly",
        day=day,
        timezone=timezone,
        now=now,
        idempotency_key=f"{idempotency_key}-open",
    )
    if refresh:
        artifact, snapshot = refresh_review_snapshot(
            service=service,
            artifact=artifact,
            runtime_dir=runtime_dir,
            generated_at=now,
            idempotency_key=f"{idempotency_key}-refresh",
        )
    else:
        from lifeos.reviews.pattern_integration import build_review_snapshot

        snapshot = build_review_snapshot(
            vault_root=service.vault_root,
            runtime_dir=runtime_dir,
            kind="weekly",
            day=day,
            generated_at=now,
        )
    required = _required(snapshot)
    return WeeklyReviewState(
        artifact,
        snapshot,
        _PROMPTS,
        required,
        weekly_due_state(artifact, now),
        _next(snapshot, artifact),
    )


def complete_weekly_review(
    *,
    service: ReviewArtifactService,
    state: WeeklyReviewState,
    now: datetime,
    idempotency_key: str,
) -> WeeklyReviewState:
    progress = ReviewProgressService(service)
    artifact = progress.update_phase(
        review_id=state.artifact.metadata.review_id,
        phase_id="weekly",
        action="complete",
        required_sections=state.required_sections,
        expected_hash=state.artifact.content_hash,
        idempotency_key=f"{idempotency_key}-phase",
        now=now,
    )
    artifact = progress.complete_review(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key=f"{idempotency_key}-review",
        now=now,
    )
    return WeeklyReviewState(
        artifact,
        state.snapshot,
        state.prompts,
        state.required_sections,
        weekly_due_state(artifact, now),
        None,
    )
