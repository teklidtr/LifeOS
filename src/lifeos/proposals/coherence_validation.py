"""Stable-target identity checks layered over ordinary proposal preflight."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lifeos.coherence import CoherenceError, collect_identity_snapshot
from lifeos.proposals.loader import LoadedProposal
from lifeos.proposals.target_identity import (
    ProposalTargetIdentityError,
    assess_proposal_target_identities,
    parse_target_identities,
)
from lifeos.proposals.validation import (
    OperationPreflightResult,
    PreflightFinding,
    ProposalPreflightResult,
    preflight_proposal as _base_preflight_proposal,
)


def preflight_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    max_inspection_bytes: int = 5 * 1024 * 1024,
) -> ProposalPreflightResult:
    """Run ordinary path/hash checks plus review-bound stable identity checks.

    Existing proposals without the LIFEOS-1643 identity extension retain the historical
    preflight behavior. Identity-bound replacement operations fail closed when their stable
    target disappears, changes identity, becomes ambiguous, changes content, or relocates.
    Relocation is deliberately not applied in place: a fresh draft/review must establish the
    new path-scoped authorization context.
    """
    base = _base_preflight_proposal(
        proposal,
        vault_root=vault_root,
        max_inspection_bytes=max_inspection_bytes,
    )
    try:
        targets = parse_target_identities(proposal.metadata, proposal.patch_document)
    except ProposalTargetIdentityError as error:
        return _invalidate(base, code="target_identity_invalid", message=str(error))
    if not targets:
        return base

    try:
        snapshot = collect_identity_snapshot(vault_root)
        resolutions = assess_proposal_target_identities(
            proposal.metadata,
            proposal.patch_document,
            snapshot,
        )
    except (CoherenceError, ProposalTargetIdentityError) as error:
        return _invalidate(base, code="target_identity_unresolvable", message=str(error))

    operations: list[OperationPreflightResult] = []
    aggregate = base.state
    for operation in base.operations:
        resolution = resolutions.get(operation.operation_id)
        if resolution is None or resolution.state == "current":
            operations.append(operation)
            continue

        invalid = resolution.state in {"ambiguous", "identity-changed"}
        state = "invalid" if invalid else "stale"
        finding = PreflightFinding(
            severity="error",
            code=f"target_identity_{resolution.state.replace('-', '_')}",
            operation_id=operation.operation_id,
            target_path=operation.target_path,
            field_path="extensions.lifeos_target_identity",
            message=resolution.detail,
        )
        operations.append(
            replace(
                operation,
                state="invalid" if operation.state == "invalid" or invalid else "stale",
                findings=(*operation.findings, finding),
            )
        )
        if state == "invalid" or aggregate == "invalid":
            aggregate = "invalid"
        elif aggregate == "valid":
            aggregate = "stale"

    return replace(base, state=aggregate, operations=tuple(operations))


def _invalidate(
    result: ProposalPreflightResult,
    *,
    code: str,
    message: str,
) -> ProposalPreflightResult:
    finding = PreflightFinding(
        severity="error",
        code=code,
        operation_id=None,
        target_path=None,
        field_path="extensions.lifeos_target_identity",
        message=message,
    )
    operations = tuple(
        replace(
            operation,
            state="invalid",
            findings=(
                *operation.findings,
                PreflightFinding(
                    severity="error",
                    code="aborted",
                    operation_id=operation.operation_id,
                    target_path=operation.target_path,
                    field_path=None,
                    message="Operation aborted because stable target identity could not be proven",
                ),
            ),
        )
        for operation in result.operations
    )
    return replace(
        result,
        state="invalid",
        operations=operations,
        findings=(*result.findings, finding),
    )
