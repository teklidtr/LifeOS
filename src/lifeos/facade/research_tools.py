"""Facade boundary for controlled external research-evidence capture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lifeos.research import ResearchError, ResearchEvidenceService, ResearchOriginKind

from .errors import ToolConflictError, ToolExecutionError, ToolValidationError
from .models import ToolDescriptor, ToolEffect

RESEARCH_CAPTURE_DESCRIPTOR = ToolDescriptor(
    name="research.capture_evidence",
    description=(
        "Capture one externally acquired evidence snapshot into canonical raw research storage "
        "with hash-bound content and acquisition lineage."
    ),
    effect=ToolEffect.CANONICAL_CAPTURE,
)


@dataclass(frozen=True, slots=True)
class ResearchEvidenceCaptureRequest:
    evidence_text: str
    source_title: str
    research_reason: str
    source_locator: str | None = None
    source_author: str | None = None
    source_publisher: str | None = None
    origin_kind: ResearchOriginKind = "query"
    origin_ref: str | None = None
    research_context: str = ""


@dataclass(frozen=True, slots=True)
class ResearchEvidenceCaptureResult:
    artifact_id: str
    source_path: str
    snapshot_hash: str
    acquisition_id: str
    created: bool
    acquisition_added: bool


def capture_research_evidence(
    *,
    vault_root: Path,
    trusted_actor_id: str,
    request: ResearchEvidenceCaptureRequest,
) -> ResearchEvidenceCaptureResult:
    """Capture evidence while keeping actor identity outside the caller-controlled request."""

    try:
        result = ResearchEvidenceService(vault_root=vault_root).capture(
            evidence_text=request.evidence_text,
            source_title=request.source_title,
            research_reason=request.research_reason,
            captured_by=trusted_actor_id,
            source_locator=request.source_locator,
            source_author=request.source_author,
            source_publisher=request.source_publisher,
            origin_kind=request.origin_kind,
            origin_ref=request.origin_ref,
            research_context=request.research_context,
        )
    except ResearchError as exc:
        if exc.code in {
            "invalid_field",
            "invalid_origin",
            "invalid_source_identity",
            "invalid_timestamp",
        }:
            raise ToolValidationError("Research evidence capture request is invalid") from exc
        if exc.code in {
            "metadata_conflict",
            "identity_mismatch",
            "snapshot_mismatch",
            "stale_artifact",
        }:
            raise ToolConflictError("Research evidence conflicts with canonical capture state") from exc
        raise ToolExecutionError("Research evidence capture failed") from exc
    artifact = result.artifact
    return ResearchEvidenceCaptureResult(
        artifact_id=artifact.metadata.artifact_id,
        source_path=artifact.relative_path,
        snapshot_hash=artifact.metadata.snapshot_hash,
        acquisition_id=result.acquisition_id,
        created=result.created,
        acquisition_added=result.acquisition_added,
    )
