"""Facade boundary for controlled external research evidence and synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lifeos.ingestion.orchestration import (
    push_research_acquisition_id,
    reset_research_acquisition_id,
)
from lifeos.ingestion.provenance import (
    push_provenance_acquisition_id,
    reset_provenance_acquisition_id,
)
from lifeos.registry import Registry
from lifeos.research import ResearchError, ResearchEvidenceService, ResearchOriginKind

from .errors import ToolConflictError, ToolExecutionError, ToolValidationError
from .models import ToolDescriptor, ToolEffect
from .proposal_tools import (
    CreateWikiProposalRequest,
    create_wiki_proposal,
)

RESEARCH_CAPTURE_DESCRIPTOR = ToolDescriptor(
    name="research.capture_evidence",
    description=(
        "Capture one externally acquired evidence snapshot into canonical raw research storage "
        "with hash-bound content and acquisition lineage."
    ),
    effect=ToolEffect.CANONICAL_CAPTURE,
)

RESEARCH_CREATE_WIKI_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="research.create_wiki_proposal",
    description=(
        "Create one reviewed draft wiki proposal from an exact captured research snapshot and "
        "selected acquisition lineage."
    ),
    effect=ToolEffect.PROPOSAL_PRODUCING,
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


@dataclass(frozen=True, slots=True)
class ResearchWikiProposalRequest:
    source_path: str
    acquisition_id: str
    target_path: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    tag_rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchWikiProposalResult:
    proposal_id: str
    proposal_path: str
    target_path: str
    status: str


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
            "metadata_mismatch",
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


def create_research_wiki_proposal(
    *,
    vault_root: Path,
    registry: Registry,
    request: ResearchWikiProposalRequest,
) -> ResearchWikiProposalResult:
    """Reuse normal ingestion while binding one exact research acquisition to provenance."""

    if not request.source_path.startswith("raw/research/"):
        raise ToolValidationError("Research synthesis source must be under raw/research/")

    try:
        source_token = push_research_acquisition_id(request.acquisition_id)
        provenance_token = push_provenance_acquisition_id(request.acquisition_id)
    except ValueError as exc:
        raise ToolValidationError("Research acquisition_id is invalid") from exc

    try:
        result = create_wiki_proposal(
            vault_root=vault_root,
            registry=registry,
            request=CreateWikiProposalRequest(
                source_path=request.source_path,
                target_path=request.target_path,
                title=request.title,
                body=request.body,
                tags=request.tags,
                tag_rationale=request.tag_rationale,
            ),
        )
    finally:
        reset_provenance_acquisition_id(provenance_token)
        reset_research_acquisition_id(source_token)

    return ResearchWikiProposalResult(
        proposal_id=result.proposal_id,
        proposal_path=result.proposal_path,
        target_path=result.target_path,
        status=result.status,
    )
