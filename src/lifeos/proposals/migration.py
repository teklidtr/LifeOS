from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .lifecycle import (
    ProposalTransitionResult,
    TransitionError,
    _transition_persistent,
)
from .loader import LoadedProposal, ProposalLoadFinding, load_proposals
from .schema import (
    ProposalMetadata,
    ProposalSchemaError,
    ProposalStatus,
    serialize_metadata,
    validate_metadata,
)

SYNTHETIC_LIFECYCLE_ACTOR = "legacy"
SYNTHETIC_REJECTION_REASON = (
    "Migrated legacy proposal without a recorded rejection reason."
)
_REVIEW_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class LegacyLifecycleMigrationCandidate:
    proposal_id: str
    proposal_path: str
    status: ProposalStatus


@dataclass(frozen=True, slots=True)
class LegacyLifecycleMigrationPlan:
    candidates: tuple[LegacyLifecycleMigrationCandidate, ...]
    skipped_proposal_ids: tuple[str, ...]
    warnings: tuple[ProposalLoadFinding, ...]


@dataclass(frozen=True, slots=True)
class LegacyLifecycleMigrationResult:
    transitions: tuple[ProposalTransitionResult, ...]
    skipped_proposal_ids: tuple[str, ...]
    warnings: tuple[ProposalLoadFinding, ...]


class LegacyLifecycleMigrationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        proposal_id: str | None = None,
        migrated_proposal_ids: tuple[str, ...] = (),
    ) -> None:
        prefix = f"{proposal_id}: " if proposal_id is not None else ""
        super().__init__(f"{code}: {prefix}{message}")
        self.code = code
        self.message = message
        self.proposal_id = proposal_id
        self.migrated_proposal_ids = migrated_proposal_ids


def migrate_legacy_metadata(
    metadata: ProposalMetadata,
    *,
    review_digest: str,
) -> ProposalMetadata:
    """Map one valid legacy metadata document to lifecycle schema version 1."""
    if metadata.lifecycle_schema_version is not None:
        raise LegacyLifecycleMigrationError(
            "not_legacy",
            "proposal already has a lifecycle schema version",
            proposal_id=metadata.id,
        )

    if (
        metadata.status is not ProposalStatus.DRAFT
        and _REVIEW_DIGEST_PATTERN.fullmatch(review_digest) is None
    ):
        raise LegacyLifecycleMigrationError(
            "invalid_review_digest",
            "review digest must be canonical lowercase SHA-256",
            proposal_id=metadata.id,
        )

    data = serialize_metadata(metadata)
    data["lifecycle_schema_version"] = 1

    if metadata.status is ProposalStatus.DRAFT:
        data.update(
            submitted_at=None,
            submitted_by=None,
            review_digest=None,
            approved_at=None,
            approved_by=None,
            rejected_at=None,
            rejected_by=None,
            rejection_reason=None,
            applied_at=None,
            applied_by=None,
        )
    else:
        data["submitted_at"] = metadata.created_at
        data["submitted_by"] = SYNTHETIC_LIFECYCLE_ACTOR
        data["review_digest"] = review_digest

        if metadata.status is ProposalStatus.PENDING:
            data.update(
                approved_at=None,
                approved_by=None,
                rejected_at=None,
                rejected_by=None,
                rejection_reason=None,
                applied_at=None,
                applied_by=None,
            )
        elif metadata.status is ProposalStatus.APPROVED:
            data["approved_by"] = metadata.approved_by or SYNTHETIC_LIFECYCLE_ACTOR
            data.update(
                rejected_at=None,
                rejected_by=None,
                rejection_reason=None,
                applied_at=None,
                applied_by=None,
            )
        elif metadata.status is ProposalStatus.REJECTED:
            data["rejected_by"] = metadata.rejected_by or SYNTHETIC_LIFECYCLE_ACTOR
            data["rejection_reason"] = (
                metadata.rejection_reason or SYNTHETIC_REJECTION_REASON
            )
            data["applied_at"] = None
            data["applied_by"] = None
            if metadata.approved_at is None:
                data["approved_by"] = None
            else:
                data["approved_by"] = (
                    metadata.approved_by or SYNTHETIC_LIFECYCLE_ACTOR
                )
        elif metadata.status is ProposalStatus.APPLIED:
            data["approved_by"] = metadata.approved_by or SYNTHETIC_LIFECYCLE_ACTOR
            data["applied_by"] = metadata.applied_by or SYNTHETIC_LIFECYCLE_ACTOR
            data.update(
                rejected_at=None,
                rejected_by=None,
                rejection_reason=None,
            )

    try:
        return validate_metadata(data)
    except ProposalSchemaError as exc:
        raise LegacyLifecycleMigrationError(
            "invalid_migrated_metadata",
            f"{exc.field_path}: {exc.message}",
            proposal_id=metadata.id,
        ) from exc



def _partition_proposals(
    proposals_root: Path,
) -> tuple[
    tuple[LoadedProposal, ...],
    tuple[str, ...],
    tuple[ProposalLoadFinding, ...],
]:
    collection = load_proposals(proposals_root)
    errors = tuple(
        finding for finding in collection.findings if finding.severity == "error"
    )
    if errors:
        first = errors[0]
        raise LegacyLifecycleMigrationError(
            "scan_failed",
            f"{first.proposal_path}: {first.code}: {first.message}",
        )

    legacy = tuple(
        proposal
        for proposal in collection.proposals
        if proposal.metadata.lifecycle_schema_version is None
    )
    skipped = tuple(
        proposal.metadata.id
        for proposal in collection.proposals
        if proposal.metadata.lifecycle_schema_version is not None
    )
    warnings = tuple(
        finding for finding in collection.findings if finding.severity == "warning"
    )
    return legacy, skipped, warnings

def plan_legacy_lifecycle_migration(
    proposals_root: Path,
) -> LegacyLifecycleMigrationPlan:
    legacy, skipped, warnings = _partition_proposals(proposals_root)
    candidates = tuple(
        LegacyLifecycleMigrationCandidate(
            proposal_id=proposal.metadata.id,
            proposal_path=proposal.proposal_path,
            status=proposal.metadata.status,
        )
        for proposal in legacy
    )
    return LegacyLifecycleMigrationPlan(candidates, skipped, warnings)


def migrate_legacy_proposal(
    proposal: LoadedProposal,
    *,
    proposals_root: Path,
) -> ProposalTransitionResult:
    if proposal.metadata.lifecycle_schema_version is not None:
        raise LegacyLifecycleMigrationError(
            "not_legacy",
            "proposal already has a lifecycle schema version",
            proposal_id=proposal.metadata.id,
        )

    def mutator(metadata: ProposalMetadata, digest: str) -> ProposalMetadata:
        return migrate_legacy_metadata(metadata, review_digest=digest)

    try:
        return _transition_persistent(proposal, proposals_root, mutator)
    except TransitionError as exc:
        raise LegacyLifecycleMigrationError(
            exc.code,
            exc.message,
            proposal_id=proposal.metadata.id,
        ) from exc


def migrate_legacy_lifecycle(
    proposals_root: Path,
) -> LegacyLifecycleMigrationResult:
    legacy, skipped, warnings = _partition_proposals(proposals_root)

    transitions: list[ProposalTransitionResult] = []
    for proposal in legacy:
        try:
            transition = migrate_legacy_proposal(
                proposal,
                proposals_root=proposals_root,
            )
        except LegacyLifecycleMigrationError as exc:
            raise LegacyLifecycleMigrationError(
                exc.code,
                exc.message,
                proposal_id=exc.proposal_id,
                migrated_proposal_ids=tuple(
                    transition.proposal_id for transition in transitions
                ),
            ) from exc
        transitions.append(transition)

    return LegacyLifecycleMigrationResult(tuple(transitions), skipped, warnings)
