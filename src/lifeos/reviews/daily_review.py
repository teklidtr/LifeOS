"""First-class daily review orchestration for morning and evening phases."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import Any, Literal

from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.contracts import ReviewArtifact, ReviewSnapshot
from lifeos.reviews.progress import ReviewProgressService
from lifeos.reviews.pattern_integration import refresh_review_snapshot

DailyPhase = Literal["morning", "evening"]


@dataclass(frozen=True, slots=True)
class DailyReviewPrompt:
    prompt_id: str
    phase_id: DailyPhase
    label: str
    optional: bool = True


@dataclass(frozen=True, slots=True)
class DailyReviewDueState:
    phase_id: DailyPhase
    state: Literal["not_started", "available", "due", "completed", "skipped"]
    reason: str


@dataclass(frozen=True, slots=True)
class DailyReviewState:
    artifact: ReviewArtifact
    snapshot: ReviewSnapshot
    active_phase: DailyPhase
    prompts: tuple[DailyReviewPrompt, ...]
    required_sections: tuple[str, ...]
    due: DailyReviewDueState
    next_section: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROMPTS: dict[DailyPhase, tuple[DailyReviewPrompt, ...]] = {
    "morning": (
        DailyReviewPrompt("morning-intent", "morning", "What deserves protection today?", False),
        DailyReviewPrompt("morning-capacity", "morning", "What is known about today's capacity?"),
        DailyReviewPrompt("morning-not-now", "morning", "What is intentionally not for today?"),
    ),
    "evening": (
        DailyReviewPrompt("evening-story", "evening", "What actually happened today?", False),
        DailyReviewPrompt("evening-friction", "evening", "What created friction or changed the plan?"),
        DailyReviewPrompt("evening-carry", "evening", "What, if anything, should be revisited later?"),
    ),
}

_REQUIRED: dict[DailyPhase, tuple[str, ...]] = {
    "morning": ("attention", "plans"),
    "evening": ("daily-evidence", "attention"),
}


def daily_due_state(artifact: ReviewArtifact, phase: DailyPhase, now: datetime) -> DailyReviewDueState:
    progress = next(item for item in artifact.metadata.phases if item.phase_id == phase)
    if progress.state == "completed":
        return DailyReviewDueState(phase, "completed", "This phase is completed and may be reopened.")
    if progress.state == "skipped":
        return DailyReviewDueState(phase, "skipped", "This phase was intentionally skipped and may be reopened.")
    local = now.timetz().replace(tzinfo=None)
    threshold = time(11, 0) if phase == "morning" else time(20, 0)
    if local >= threshold:
        return DailyReviewDueState(phase, "due", f"The {phase} phase is still open after {threshold.strftime('%H:%M')}.")
    return DailyReviewDueState(phase, "available", f"The {phase} phase is available but not due.")


def _next_section(snapshot: ReviewSnapshot, phase: DailyPhase, artifact: ReviewArtifact) -> str | None:
    progress = next(item for item in artifact.metadata.phases if item.phase_id == phase)
    accounted = set(progress.completed_sections) | set(progress.skipped_sections)
    for section_id in _REQUIRED[phase]:
        if section_id not in accounted:
            return section_id
    for section in snapshot.sections:
        if section.section_id not in accounted and section.state == "ready":
            return section.section_id
    return None


def open_daily_review(
    *,
    service: ReviewArtifactService,
    runtime_dir: Any,
    day: date,
    timezone: str,
    now: datetime,
    idempotency_key: str,
    phase: DailyPhase = "morning",
    refresh: bool = True,
    urgent_pattern_ids: tuple[str, ...] = (),
    pinned_pattern_ids: tuple[str, ...] = (),
) -> DailyReviewState:
    artifact = service.open_or_create(
        kind="daily",
        day=day,
        timezone=timezone,
        now=now,
        idempotency_key=f"{idempotency_key}-open",
    )
    if artifact.metadata.current_phase != phase:
        artifact = service.update(
            review_id=artifact.metadata.review_id,
            expected_hash=artifact.content_hash,
            idempotency_key=f"{idempotency_key}-phase",
            now=now,
            update=ReviewArtifactUpdate(current_phase=phase),
        )
    if refresh:
        artifact, snapshot = refresh_review_snapshot(
            service=service,
            artifact=artifact,
            runtime_dir=runtime_dir,
            generated_at=now,
            idempotency_key=f"{idempotency_key}-refresh",
            urgent_pattern_ids=urgent_pattern_ids,
            pinned_pattern_ids=pinned_pattern_ids,
        )
    else:
        from lifeos.reviews.pattern_integration import build_review_snapshot

        snapshot = build_review_snapshot(
            vault_root=service.vault_root,
            runtime_dir=runtime_dir,
            kind="daily",
            day=day,
            generated_at=now,
            urgent_pattern_ids=urgent_pattern_ids,
            pinned_pattern_ids=pinned_pattern_ids,
        )
    return DailyReviewState(
        artifact,
        snapshot,
        phase,
        _PROMPTS[phase],
        _REQUIRED[phase],
        daily_due_state(artifact, phase, now),
        _next_section(snapshot, phase, artifact),
    )


def complete_daily_phase(
    *,
    service: ReviewArtifactService,
    runtime_dir: Any,
    state: DailyReviewState,
    now: datetime,
    idempotency_key: str,
) -> DailyReviewState:
    artifact = ReviewProgressService(service).update_phase(
        review_id=state.artifact.metadata.review_id,
        phase_id=state.active_phase,
        action="complete",
        required_sections=state.required_sections,
        expected_hash=state.artifact.content_hash,
        idempotency_key=idempotency_key,
        now=now,
    )
    return DailyReviewState(
        artifact,
        state.snapshot,
        state.active_phase,
        state.prompts,
        state.required_sections,
        daily_due_state(artifact, state.active_phase, now),
        _next_section(state.snapshot, state.active_phase, artifact),
    )
