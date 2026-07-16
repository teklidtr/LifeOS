"""Versioned contracts for canonical daily and weekly review artifacts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal, Mapping, Sequence

REVIEW_SCHEMA_VERSION = 1
SUPPORTED_REVIEW_SCHEMA_VERSIONS = (1,)

ReviewKind = Literal["daily", "weekly"]
ReviewStatus = Literal["open", "completed", "skipped", "superseded"]
PhaseId = Literal["morning", "evening", "weekly"]
ProgressState = Literal["pending", "completed", "skipped"]
SectionState = Literal["ready", "empty", "unavailable"]
DecisionKind = Literal[
    "acknowledge",
    "carry",
    "defer_review",
    "clarify",
    "dismiss_for_review",
    "open_source",
    "propose_change",
]

_HASH = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_REVIEW_ID = re.compile(r"^(daily-\d{4}-\d{2}-\d{2}|weekly-\d{4}-W\d{2})$")
_ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,191}$")
_TIMEZONE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-/]{0,127}$")


class ReviewContractError(ValueError):
    """Raised when a review artifact contract is malformed or incompatible."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True, slots=True)
class ReviewSourceReference:
    path: str
    content_hash: str | None = None
    detail: str | None = None
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewItemSnapshot:
    item_id: str
    section_id: str
    title: str
    detail: str
    evidence_fingerprint: str
    state: SectionState = "ready"
    action: str | None = None
    sources: tuple[ReviewSourceReference, ...] = ()
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewSectionSnapshot:
    section_id: str
    title: str
    optional: bool
    state: SectionState
    items: tuple[ReviewItemSnapshot, ...] = ()
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    snapshot_id: str
    generated_at: str
    content_hash: str
    sections: tuple[ReviewSectionSnapshot, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewPhaseProgress:
    phase_id: PhaseId
    state: ProgressState = "pending"
    completed_sections: tuple[str, ...] = ()
    skipped_sections: tuple[str, ...] = ()
    current_section: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewItemDecision:
    item_id: str
    evidence_fingerprint: str
    decision: DecisionKind
    decided_at: str
    note: str | None = None
    proposal_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewAnswer:
    prompt_id: str
    value: str
    answered_at: str
    phase_id: PhaseId | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewArtifactMetadata:
    review_id: str
    schema_version: int
    review_kind: ReviewKind
    period_start: date
    period_end: date
    timezone: str
    status: ReviewStatus
    created_at: str
    updated_at: str
    phases: tuple[ReviewPhaseProgress, ...]
    current_phase: PhaseId | None = None
    item_decisions: tuple[ReviewItemDecision, ...] = ()
    answers: tuple[ReviewAnswer, ...] = ()
    proposal_refs: tuple[str, ...] = ()
    previous_review_id: str | None = None
    next_review_id: str | None = None
    migrated_from: tuple[str, ...] = ()
    snapshot_id: str | None = None
    snapshot_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewArtifact:
    path: str
    content_hash: str
    metadata: ReviewArtifactMetadata
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "metadata": self.metadata.to_dict(),
            "body": self.body,
        }


def review_identity(kind: ReviewKind, day: date) -> tuple[str, date, date]:
    if kind == "daily":
        return f"daily-{day.isoformat()}", day, day
    if kind == "weekly":
        start = day - timedelta(days=day.weekday())
        iso = start.isocalendar()
        return f"weekly-{iso.year}-W{iso.week:02d}", start, start + timedelta(days=6)
    raise ReviewContractError("invalid_review_kind", f"Unsupported review kind: {kind}", "review_kind")


def review_path(kind: ReviewKind, day: date) -> str:
    review_id, _, _ = review_identity(kind, day)
    suffix = review_id.removeprefix(f"{kind}-")
    return f"reviews/{kind}/{suffix}.md"


def review_kind_from_legacy(kind: str) -> ReviewKind:
    if kind in {"morning", "evening", "daily"}:
        return "daily"
    if kind == "weekly":
        return "weekly"
    raise ReviewContractError("invalid_review_kind", f"Unsupported review kind: {kind}", "review_kind")


def phase_ids_for_kind(kind: ReviewKind) -> tuple[PhaseId, ...]:
    return ("morning", "evening") if kind == "daily" else ("weekly",)


def default_phases(kind: ReviewKind) -> tuple[ReviewPhaseProgress, ...]:
    return tuple(ReviewPhaseProgress(phase_id) for phase_id in phase_ids_for_kind(kind))


def stable_fingerprint(*parts: object) -> str:
    payload = "\x00".join(str(part) for part in parts)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _date(value: object, field: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ReviewContractError("invalid_date", f"{field} must be an ISO date.", field) from exc
    raise ReviewContractError("invalid_date", f"{field} must be an ISO date.", field)


def _datetime(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewContractError("invalid_datetime", f"{field} must be an ISO datetime.", field)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReviewContractError("invalid_datetime", f"{field} must be an ISO datetime.", field) from exc
    if parsed.tzinfo is None:
        raise ReviewContractError("invalid_datetime", f"{field} must include a timezone.", field)
    return value


def _string(value: object, field: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewContractError("invalid_string", f"{field} must be a non-empty string.", field)
    result = value.strip()
    if pattern is not None and pattern.fullmatch(result) is None:
        raise ReviewContractError("invalid_string", f"{field} has an invalid format.", field)
    return result


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ReviewContractError("invalid_collection", f"{field} must be a list of strings.", field)
    rows = tuple(_string(item, field) for item in value)
    if len(set(rows)) != len(rows):
        raise ReviewContractError("duplicate_value", f"{field} contains duplicates.", field)
    return rows


def _hash(value: object, field: str) -> str:
    result = _string(value, field)
    if _HASH.fullmatch(result) is None:
        raise ReviewContractError("invalid_hash", f"{field} must be a SHA-256 hash.", field)
    return result if result.startswith("sha256:") else f"sha256:{result}"


def _path(value: object, field: str) -> str:
    result = _string(value, field)
    if "\\" in result or "\x00" in result:
        raise ReviewContractError("invalid_path", f"{field} is not a safe vault-relative path.", field)
    pure = PurePosixPath(result)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ReviewContractError("invalid_path", f"{field} is not a safe vault-relative path.", field)
    return pure.as_posix()


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewContractError("invalid_mapping", f"{field} must be a mapping.", field)
    return value


def parse_phase_progress(value: object, *, field: str = "phases") -> ReviewPhaseProgress:
    raw = _mapping(value, field)
    phase_id = _string(raw.get("phase_id"), f"{field}.phase_id")
    if phase_id not in {"morning", "evening", "weekly"}:
        raise ReviewContractError("invalid_phase", f"Unsupported phase: {phase_id}", f"{field}.phase_id")
    state = str(raw.get("state", "pending"))
    if state not in {"pending", "completed", "skipped"}:
        raise ReviewContractError("invalid_progress_state", f"Unsupported phase state: {state}", f"{field}.state")
    completed_at = _optional_string(raw.get("completed_at"), f"{field}.completed_at")
    if completed_at is not None:
        completed_at = _datetime(completed_at, f"{field}.completed_at")
    completed = _string_tuple(raw.get("completed_sections", []), f"{field}.completed_sections")
    skipped = _string_tuple(raw.get("skipped_sections", []), f"{field}.skipped_sections")
    overlap = set(completed) & set(skipped)
    if overlap:
        raise ReviewContractError("conflicting_progress", f"Sections cannot be completed and skipped: {sorted(overlap)}", field)
    return ReviewPhaseProgress(
        phase_id=phase_id,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        completed_sections=completed,
        skipped_sections=skipped,
        current_section=_optional_string(raw.get("current_section"), f"{field}.current_section"),
        completed_at=completed_at,
    )


def parse_item_decision(value: object, *, field: str = "item_decisions") -> ReviewItemDecision:
    raw = _mapping(value, field)
    decision = _string(raw.get("decision"), f"{field}.decision")
    allowed = {
        "acknowledge",
        "carry",
        "defer_review",
        "clarify",
        "dismiss_for_review",
        "open_source",
        "propose_change",
    }
    if decision not in allowed:
        raise ReviewContractError("invalid_decision", f"Unsupported review decision: {decision}", f"{field}.decision")
    return ReviewItemDecision(
        item_id=_string(raw.get("item_id"), f"{field}.item_id", pattern=_ITEM_ID),
        evidence_fingerprint=_hash(raw.get("evidence_fingerprint"), f"{field}.evidence_fingerprint"),
        decision=decision,  # type: ignore[arg-type]
        decided_at=_datetime(raw.get("decided_at"), f"{field}.decided_at"),
        note=_optional_string(raw.get("note"), f"{field}.note"),
        proposal_id=_optional_string(raw.get("proposal_id"), f"{field}.proposal_id"),
    )


def parse_answer(value: object, *, field: str = "answers") -> ReviewAnswer:
    raw = _mapping(value, field)
    phase = _optional_string(raw.get("phase_id"), f"{field}.phase_id")
    if phase is not None and phase not in {"morning", "evening", "weekly"}:
        raise ReviewContractError("invalid_phase", f"Unsupported phase: {phase}", f"{field}.phase_id")
    return ReviewAnswer(
        prompt_id=_string(raw.get("prompt_id"), f"{field}.prompt_id", pattern=_ITEM_ID),
        value=_string(raw.get("value"), f"{field}.value"),
        answered_at=_datetime(raw.get("answered_at"), f"{field}.answered_at"),
        phase_id=phase,  # type: ignore[arg-type]
    )


def validate_review_metadata(
    frontmatter: Mapping[str, Any], *, path: str | None = None
) -> ReviewArtifactMetadata:
    schema = frontmatter.get("review_schema", frontmatter.get("schema_version"))
    if type(schema) is not int:
        raise ReviewContractError("missing_schema", "review_schema must be an integer.", "review_schema")
    if schema not in SUPPORTED_REVIEW_SCHEMA_VERSIONS:
        raise ReviewContractError(
            "unsupported_schema",
            f"Review schema {schema} is unsupported; supported versions: {SUPPORTED_REVIEW_SCHEMA_VERSIONS}.",
            "review_schema",
        )
    review_id = _string(frontmatter.get("review_id"), "review_id", pattern=_REVIEW_ID)
    kind = _string(frontmatter.get("review_kind"), "review_kind")
    if kind not in {"daily", "weekly"}:
        raise ReviewContractError("invalid_review_kind", f"Unsupported review kind: {kind}", "review_kind")
    start = _date(frontmatter.get("period_start"), "period_start")
    end = _date(frontmatter.get("period_end"), "period_end")
    expected_id, expected_start, expected_end = review_identity(kind, start)  # type: ignore[arg-type]
    if (review_id, start, end) != (expected_id, expected_start, expected_end):
        raise ReviewContractError(
            "identity_mismatch",
            f"Review identity or period does not match {kind} date rules.",
            "review_id",
        )
    if path is not None and _path(path, "path") != review_path(kind, start):  # type: ignore[arg-type]
        raise ReviewContractError("path_mismatch", "Review path does not match its identity.", "path")
    timezone = _string(frontmatter.get("timezone"), "timezone", pattern=_TIMEZONE)
    status = _string(frontmatter.get("status"), "status")
    if status not in {"open", "completed", "skipped", "superseded"}:
        raise ReviewContractError("invalid_status", f"Unsupported review status: {status}", "status")
    raw_phases = frontmatter.get("phases")
    if not isinstance(raw_phases, Sequence) or isinstance(raw_phases, (str, bytes)):
        raise ReviewContractError("invalid_collection", "phases must be a list.", "phases")
    phases = tuple(parse_phase_progress(value, field=f"phases[{index}]") for index, value in enumerate(raw_phases))
    expected_phases = phase_ids_for_kind(kind)  # type: ignore[arg-type]
    ids = tuple(phase.phase_id for phase in phases)
    if ids != expected_phases:
        raise ReviewContractError("invalid_phases", f"Expected phases {expected_phases}, got {ids}.", "phases")
    current_phase = _optional_string(frontmatter.get("current_phase"), "current_phase")
    if current_phase is not None and current_phase not in expected_phases:
        raise ReviewContractError("invalid_phase", "current_phase is not valid for this review.", "current_phase")
    decisions_raw = frontmatter.get("item_decisions", [])
    if not isinstance(decisions_raw, Sequence) or isinstance(decisions_raw, (str, bytes)):
        raise ReviewContractError("invalid_collection", "item_decisions must be a list.", "item_decisions")
    decisions = tuple(parse_item_decision(value, field=f"item_decisions[{index}]") for index, value in enumerate(decisions_raw))
    decision_keys = [(item.item_id, item.evidence_fingerprint) for item in decisions]
    if len(set(decision_keys)) != len(decision_keys):
        raise ReviewContractError("duplicate_decision", "item_decisions contains duplicate item fingerprints.", "item_decisions")
    answers_raw = frontmatter.get("answers", [])
    if not isinstance(answers_raw, Sequence) or isinstance(answers_raw, (str, bytes)):
        raise ReviewContractError("invalid_collection", "answers must be a list.", "answers")
    answers = tuple(parse_answer(value, field=f"answers[{index}]") for index, value in enumerate(answers_raw))
    answer_keys = [(answer.prompt_id, answer.phase_id) for answer in answers]
    if len(set(answer_keys)) != len(answer_keys):
        raise ReviewContractError("duplicate_answer", "answers contains duplicate prompt and phase pairs.", "answers")
    snapshot_hash = frontmatter.get("snapshot_hash")
    normalized_snapshot_hash = None if snapshot_hash is None else _hash(snapshot_hash, "snapshot_hash")
    return ReviewArtifactMetadata(
        review_id=review_id,
        schema_version=schema,
        review_kind=kind,  # type: ignore[arg-type]
        period_start=start,
        period_end=end,
        timezone=timezone,
        status=status,  # type: ignore[arg-type]
        created_at=_datetime(frontmatter.get("created_at"), "created_at"),
        updated_at=_datetime(frontmatter.get("updated_at"), "updated_at"),
        phases=phases,
        current_phase=current_phase,  # type: ignore[arg-type]
        item_decisions=decisions,
        answers=answers,
        proposal_refs=_string_tuple(frontmatter.get("proposal_refs", []), "proposal_refs"),
        previous_review_id=_optional_string(frontmatter.get("previous_review_id"), "previous_review_id"),
        next_review_id=_optional_string(frontmatter.get("next_review_id"), "next_review_id"),
        migrated_from=tuple(_path(item, "migrated_from") for item in _string_tuple(frontmatter.get("migrated_from", []), "migrated_from")),
        snapshot_id=_optional_string(frontmatter.get("snapshot_id"), "snapshot_id"),
        snapshot_hash=normalized_snapshot_hash,
    )
