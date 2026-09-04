"""Deterministic, disposable read model for canonical personal patterns."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from lifeos.diagnostics import DomainDiagnostic
from lifeos.observation import ObservationError, ObservationRecord, load_observations
from lifeos.publication import (
    PublicationError,
    active_generation_path,
    inspect_generation_integrity,
    publish_generation,
)
from lifeos.registry import Registry
from lifeos.vault import VaultAccessError, VaultMarkdownFile, iter_vault_markdown

from .artifact import parse_pattern
from .contracts import (
    PatternArtifact,
    PatternConfidence,
    PatternError,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    PatternStatus,
)
from .evidence import (
    EvidencePathPredicate,
    PatternEvidenceDiagnostic,
    resolve_evidence_states,
)
from .review import (
    PatternReviewAssessment,
    PatternReviewReason,
    ReviewRecommendation,
    assess_pattern_review,
)

PERSONAL_MODEL_SCHEMA_VERSION = 1
EvidenceHealth = Literal["none", "healthy", "attention", "unavailable"]


class PersonalModelError(RuntimeError):
    """Raised when the disposable Personal Model cannot be built or inspected safely."""


@dataclass(frozen=True, slots=True)
class PersonalModelItem:
    """One lightweight derived view over a unique canonical pattern."""

    pattern_id: str
    pattern_path: str
    pattern_content_hash: str
    title: str
    description: str
    status: PatternStatus
    confidence: PatternConfidence
    review_reasons: tuple[str, ...]
    origin: PatternOrigin
    last_reviewed_at: str | None
    review_due_at: str | None
    review_due: bool
    evidence_fingerprint: str
    evidence: tuple[PatternEvidence, ...]
    evidence_health: EvidenceHealth
    evidence_diagnostics: tuple[PatternEvidenceDiagnostic, ...]
    freshness_days: int | None
    review_recommendation: ReviewRecommendation
    review_trigger_reasons: tuple[PatternReviewReason, ...]


@dataclass(frozen=True, slots=True)
class PersonalModelDocument:
    """Typed aggregate view. Canonical meaning remains in ``patterns/*.md``."""

    schema_version: int
    source_hash: str
    active: tuple[PersonalModelItem, ...]
    seeds: tuple[PersonalModelItem, ...]
    needs_review: tuple[PersonalModelItem, ...]
    archived: tuple[PersonalModelItem, ...]
    diagnostics: tuple[DomainDiagnostic, ...]

    @property
    def items(self) -> tuple[PersonalModelItem, ...]:
        return (*self.active, *self.seeds, *self.needs_review, *self.archived)


def _moment(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PersonalModelError("Personal Model evaluation time must include a timezone.")
    return moment


def _sources(vault_root: Path) -> tuple[VaultMarkdownFile, ...]:
    try:
        return iter_vault_markdown(vault_root, roots=("patterns",))
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return ()
        raise PersonalModelError(str(exc)) from exc


def _source_hash(sources: tuple[VaultMarkdownFile, ...]) -> str:
    hasher = hashlib.sha256()
    for source in sources:
        path = source.relative_path.encode("utf-8")
        hasher.update(len(path).to_bytes(4, "big"))
        hasher.update(path)
        hasher.update(hashlib.sha256(source.content_bytes).digest())
    return "sha256:" + hasher.hexdigest()


def _message(value: str) -> str:
    return " ".join(value.split())[:300]


def _pattern_diagnostic(path: str, error: PatternError) -> DomainDiagnostic:
    raw_line = error.data.get("line")
    line = raw_line if type(raw_line) is int and raw_line > 0 else 1
    return DomainDiagnostic(
        code=error.code,
        severity="error",
        source_path=path,
        line=line,
        message=_message(error.message),
    )


def _observation_diagnostic(error: ObservationError) -> DomainDiagnostic:
    if error.diagnostic is not None:
        return error.diagnostic
    return DomainDiagnostic(
        code="observation-unavailable",
        severity="error",
        source_path="journal",
        line=1,
        message=_message(str(error)),
    )


def _parse_unique_patterns(
    sources: tuple[VaultMarkdownFile, ...],
) -> tuple[tuple[PatternArtifact, ...], tuple[DomainDiagnostic, ...]]:
    parsed: list[PatternArtifact] = []
    diagnostics: list[DomainDiagnostic] = []
    for source in sources:
        try:
            artifact = parse_pattern(source.path, source.relative_path, source.content)
        except PatternError as exc:
            diagnostics.append(_pattern_diagnostic(source.relative_path, exc))
            continue
        if artifact is not None:
            parsed.append(artifact)

    by_id: dict[str, list[PatternArtifact]] = {}
    for artifact in parsed:
        by_id.setdefault(artifact.metadata.pattern_id, []).append(artifact)

    duplicate_ids = {pattern_id for pattern_id, items in by_id.items() if len(items) > 1}
    for pattern_id in sorted(duplicate_ids):
        paths = tuple(sorted(item.path for item in by_id[pattern_id]))
        rendered_paths = ", ".join(paths)
        for path in paths:
            diagnostics.append(
                DomainDiagnostic(
                    code="duplicate_identity",
                    severity="error",
                    source_path=path,
                    line=1,
                    message=_message(
                        f"Pattern id {pattern_id!r} is declared by multiple canonical files: "
                        f"{rendered_paths}."
                    ),
                )
            )

    unique = tuple(
        sorted(
            (item for item in parsed if item.metadata.pattern_id not in duplicate_ids),
            key=lambda item: (item.metadata.pattern_id, item.path),
        )
    )
    return unique, _sorted_diagnostics(diagnostics)


def _sorted_diagnostics(items: list[DomainDiagnostic]) -> tuple[DomainDiagnostic, ...]:
    return tuple(
        sorted(
            set(items),
            key=lambda item: (
                item.source_path,
                item.line,
                item.code,
                item.severity,
                item.message,
            ),
        )
    )


def _evidence_health(
    evidence: tuple[PatternEvidence, ...],
    diagnostics: tuple[PatternEvidenceDiagnostic, ...],
) -> EvidenceHealth:
    if not evidence:
        return "none"
    states = {item.state for item in diagnostics}
    if not states:
        return "unavailable"
    if states == {"unchanged"}:
        return "healthy"
    if states & {"missing", "deleted", "ambiguous"}:
        return "unavailable"
    return "attention"


def _review_due(metadata: PatternMetadata, *, now: datetime) -> bool:
    if metadata.review_due_at is None:
        return False
    due = datetime.fromisoformat(metadata.review_due_at.replace("Z", "+00:00"))
    return due <= now


def _factual_only_artifact(artifact: PatternArtifact) -> PatternArtifact:
    return replace(artifact, metadata=replace(artifact.metadata, evaluation=None))


def _freshness_days(assessment: PatternReviewAssessment) -> int | None:
    report = assessment.current_analysis
    if report is None or not report.candidates:
        return None
    return report.candidates[0].freshness_days


def _assessment(
    *,
    artifact: PatternArtifact,
    observations: tuple[ObservationRecord, ...],
    observations_available: bool,
    evidence_diagnostics: tuple[PatternEvidenceDiagnostic, ...],
    now: datetime,
) -> tuple[PatternReviewAssessment, DomainDiagnostic | None]:
    evaluate = artifact.metadata.evaluation is not None
    if evaluate and not observations_available:
        return (
            assess_pattern_review(
                artifact=_factual_only_artifact(artifact),
                observations=(),
                evidence_diagnostics=evidence_diagnostics,
                now=now,
            ),
            None,
        )
    try:
        return (
            assess_pattern_review(
                artifact=artifact,
                observations=observations,
                evidence_diagnostics=evidence_diagnostics,
                now=now,
            ),
            None,
        )
    except PatternError as exc:
        fallback = assess_pattern_review(
            artifact=_factual_only_artifact(artifact),
            observations=(),
            evidence_diagnostics=evidence_diagnostics,
            now=now,
        )
        return fallback, _pattern_diagnostic(artifact.path, exc)


def _item(
    *,
    artifact: PatternArtifact,
    evidence_diagnostics: tuple[PatternEvidenceDiagnostic, ...],
    assessment: PatternReviewAssessment,
    now: datetime,
) -> PersonalModelItem:
    metadata = artifact.metadata
    return PersonalModelItem(
        pattern_id=metadata.pattern_id,
        pattern_path=artifact.path,
        pattern_content_hash=artifact.content_hash,
        title=metadata.title,
        description=metadata.description,
        status=metadata.status,
        confidence=metadata.confidence,
        review_reasons=metadata.review_reasons,
        origin=metadata.origin,
        last_reviewed_at=metadata.last_reviewed_at,
        review_due_at=metadata.review_due_at,
        review_due=_review_due(metadata, now=now),
        evidence_fingerprint=metadata.evidence_fingerprint,
        evidence=metadata.evidence,
        evidence_health=_evidence_health(metadata.evidence, evidence_diagnostics),
        evidence_diagnostics=evidence_diagnostics,
        freshness_days=_freshness_days(assessment),
        review_recommendation=assessment.recommendation,
        review_trigger_reasons=assessment.reasons,
    )


def build_personal_model_document(
    *,
    vault_root: Path,
    registry: Registry,
    allow_path: EvidencePathPredicate,
    now: datetime | None = None,
) -> PersonalModelDocument:
    """Rebuild a typed Personal Model entirely from canonical patterns and current facts."""
    moment = _moment(now)
    sources = _sources(vault_root)
    artifacts, parsed_diagnostics = _parse_unique_patterns(sources)
    diagnostics = list(parsed_diagnostics)

    observations: tuple[ObservationRecord, ...] = ()
    observations_available = True
    if any(item.metadata.evaluation is not None for item in artifacts):
        try:
            observations = tuple(
                item for item in load_observations(vault_root) if allow_path(item.path)
            )
        except ObservationError as exc:
            diagnostics.append(_observation_diagnostic(exc))
            observations_available = False

    items: list[PersonalModelItem] = []
    for artifact in artifacts:
        evidence_diagnostics = resolve_evidence_states(
            registry,
            artifact.metadata.evidence,
            allow_path=allow_path,
        )
        assessment, assessment_diagnostic = _assessment(
            artifact=artifact,
            observations=observations,
            observations_available=observations_available,
            evidence_diagnostics=evidence_diagnostics,
            now=moment,
        )
        if assessment_diagnostic is not None:
            diagnostics.append(assessment_diagnostic)
        items.append(
            _item(
                artifact=artifact,
                evidence_diagnostics=evidence_diagnostics,
                assessment=assessment,
                now=moment,
            )
        )

    ordered = tuple(sorted(items, key=lambda item: (item.pattern_id, item.pattern_path)))
    return PersonalModelDocument(
        schema_version=PERSONAL_MODEL_SCHEMA_VERSION,
        source_hash=_source_hash(sources),
        active=tuple(item for item in ordered if item.status == "active"),
        seeds=tuple(item for item in ordered if item.status == "seed"),
        needs_review=tuple(item for item in ordered if item.status == "needs-review"),
        archived=tuple(item for item in ordered if item.status == "archived"),
        diagnostics=_sorted_diagnostics(diagnostics),
    )


def serialize_personal_model(document: PersonalModelDocument) -> bytes:
    """Serialize the disposable model deterministically for inspection and publication."""
    return (
        json.dumps(asdict(document), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


class PersonalModelService:
    """Publish a crash-consistent Personal Model generation under ``.lifeos/``."""

    def __init__(
        self,
        *,
        vault_root: Path,
        runtime_dir: Path,
        registry: Registry,
        allow_path: EvidencePathPredicate,
    ) -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.registry = registry
        self.allow_path = allow_path

    @property
    def root(self) -> Path:
        return self.runtime_dir / "personal-model"

    def rebuild(self, *, now: datetime | None = None) -> PersonalModelDocument:
        document = build_personal_model_document(
            vault_root=self.vault_root,
            registry=self.registry,
            allow_path=self.allow_path,
            now=now,
        )
        try:
            publish_generation(
                root=self.root,
                files={"model.json": serialize_personal_model(document)},
            )
        except PublicationError as exc:
            raise PersonalModelError(str(exc)) from exc
        return document

    def active_path(self) -> Path | None:
        """Return the validated active generation path, or None when a rebuild is needed."""
        try:
            generation = active_generation_path(self.root)
        except PublicationError as exc:
            raise PersonalModelError(str(exc)) from exc
        if generation is None:
            return None
        integrity = inspect_generation_integrity(generation)
        if integrity.state != "valid":
            raise PersonalModelError(
                f"Personal Model generation is {integrity.state}: {integrity.code}."
            )
        return generation
