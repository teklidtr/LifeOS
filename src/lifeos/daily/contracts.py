"""Typed contracts shared by the Obsidian bridge and daily services."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

CaptureKind = Literal["thought", "task", "project", "journal", "flashcard", "metric"]
Outcome = Literal["started", "done", "partial", "skipped", "deferred", "cancelled"]
Level = Literal["low", "medium", "high"]
ReviewKind = Literal["morning", "evening", "weekly"]


@dataclass(frozen=True, slots=True)
class CanonicalReference:
    path: str
    content_hash: str
    note_id: str | None = None
    block: str | None = None


@dataclass(frozen=True, slots=True)
class MutationResult:
    operation: str
    reference: CanonicalReference
    idempotency_key: str
    created: bool
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class QuickCaptureRequest:
    idempotency_key: str
    kind: CaptureKind
    title: str
    content: str = ""
    target_path: str | None = None
    plan_path: str | None = None
    task: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    expected_hash: str | None = None


@dataclass(frozen=True, slots=True)
class CheckInRequest:
    idempotency_key: str
    day: date
    period: Literal["morning", "evening"]
    metrics: dict[str, int | float | str]
    activities: tuple[str, ...] = ()
    note: str = ""
    expected_hash: str | None = None


@dataclass(frozen=True, slots=True)
class TaskOutcomeRequest:
    idempotency_key: str
    plan_path: str
    task_id: str
    outcome: Outcome
    day: date
    expected_hash: str
    planned_minutes: int | None = None
    actual_minutes: int | None = None
    energy_before: Level | None = None
    energy_after: Level | None = None
    motivation_before: Level | None = None
    difficulty: int | None = None
    satisfaction: int | None = None
    reason: str | None = None
    note: str | None = None
    deferred_until: date | None = None
    started_at: str | None = None
    ended_at: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewNoteRequest:
    idempotency_key: str
    kind: ReviewKind
    day: date
    facts_markdown: str
    expected_hash: str | None = None
