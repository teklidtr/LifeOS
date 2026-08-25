"""Stable-target identity checks layered over ordinary proposal preflight."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import collect_scoped_identity_snapshot, runtime_exclusion_prefix
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
from lifeos.retrieval.contracts import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy


def preflight_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    max_inspection_bytes: int = 5 * 1024 * 1024,
    runtime_dir: Path | None = None,
) -> ProposalPreflightResult:
    """Run ordinary path/hash checks plus review-bound stable identity checks.

    Existing proposals without the LIFEOS-1643 identity extension retain the historical
    preflight behavior. Identity-bound replacement operations fail closed when their stable
    target disappears, changes identity, becomes ambiguous, changes content, or relocates.
    Relocation is deliberately not applied in place: a fresh draft/review must establish the
    new path-scoped authorization context.

    Identity discovery is policy-scoped before Markdown is opened. An explicitly reviewed
    target may authorize protected-scope intent for that exact path only; unrelated protected
    or excluded notes cannot be read or influence the proposal result merely because they share
    the same frontmatter id. Config-aware callers pass ``runtime_dir`` explicitly so disposable
    custom-runtime Markdown stays outside canonical identity even when the config file itself
    lives outside the vault.
    """
    base = _base_preflight_proposal(
        proposal,
        vault_root=vault_root,
        max_inspection_bytes=max_inspection_bytes,
    )
    try:
        runtime_prefix = runtime_exclusion_prefix(vault_root, runtime_dir=runtime_dir)
    except CoherenceError as error:
        return _invalidate(base, code="runtime_scope_unresolvable", message=str(error))
    if runtime_prefix is not None:
        runtime_targets = sorted(
            {
                operation.target_path
                for operation in base.operations
                if operation.target_path.startswith(runtime_prefix)
            }
        )
        if runtime_targets:
            return _invalidate(
                base,
                code="target_inside_runtime",
                message=(
                    "Proposal targets configured node-local runtime state rather than canonical "
                    "vault content: " + ", ".join(runtime_targets)
                ),
            )

    try:
        targets = parse_target_identities(proposal.metadata, proposal.patch_document)
    except ProposalTargetIdentityError as error:
        return _invalidate(base, code="target_identity_invalid", message=str(error))
    if not targets:
        return base

    reviewed_paths = frozenset(target.reviewed_path for target in targets)
    try:
        policy = load_retrieval_policy(vault_root)

        def allow_identity_path(path: str) -> bool:
            if path.startswith("conversations/") or path.startswith("proposals/"):
                return False
            decision = scope_decision(
                path,
                scope=RetrievalScope(allow_protected=path in reviewed_paths),
                policy=policy,
                mode="local",
            )
            return decision.allowed

        snapshot = collect_scoped_identity_snapshot(
            vault_root,
            allow_path=allow_identity_path,
            runtime_dir=runtime_dir,
        )
        resolutions = assess_proposal_target_identities(
            proposal.metadata,
            proposal.patch_document,
            snapshot,
        )
    except (CoherenceError, ProposalTargetIdentityError, RetrievalError) as error:
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
        message = resolution.detail
        if resolution.current_path is not None and resolution.current_path != resolution.reviewed_path:
            message = (
                f"{message} Current stable-id location: {resolution.current_path}. "
                f"Reviewed location: {resolution.reviewed_path}."
            )
        finding = PreflightFinding(
            severity="error",
            code=f"target_identity_{resolution.state.replace('-', '_')}",
            operation_id=operation.operation_id,
            target_path=operation.target_path,
            field_path="extensions.lifeos_target_identity",
            message=message,
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
