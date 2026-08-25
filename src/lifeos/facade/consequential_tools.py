from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from lifeos.facade.authorization import (
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
    ConsequentialAuthorizer,
)
from lifeos.facade.errors import (
    ToolAuthorizationError,
    ToolConflictError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRecoveryRequiredError,
    ToolUnavailableError,
)
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.proposals.application import ApplicationError, ApplicationErrorCode, apply_proposal
from lifeos.proposals.lifecycle import (
    TransitionError,
    approve_proposal,
    compute_review_digest,
    submit_proposal_for_review,
)
from lifeos.proposals.loader import load_proposal_directory, LoadedProposal

SUBMIT_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="proposal.submit",
    description="Submit a draft proposal for human review.",
    effect=ToolEffect.CONSEQUENTIAL,
)

APPROVE_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="proposal.approve",
    description="Approve a pending proposal. Must be authorized by a human.",
    effect=ToolEffect.CONSEQUENTIAL,
)

APPLY_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="proposal.apply",
    description="Apply an approved proposal to the vault.",
    effect=ToolEffect.CONSEQUENTIAL,
)

@dataclass(frozen=True, slots=True)
class SubmitProposalRequest:
    proposal_id: str


@dataclass(frozen=True, slots=True)
class SubmitProposalResult:
    proposal_id: str
    status: Literal["pending"]
    review_digest: str


@dataclass(frozen=True, slots=True)
class ApproveProposalRequest:
    proposal_id: str


@dataclass(frozen=True, slots=True)
class ApproveProposalResult:
    proposal_id: str
    status: Literal["approved"]
    review_digest: str


@dataclass(frozen=True, slots=True)
class ApplyProposalRequest:
    proposal_id: str


@dataclass(frozen=True, slots=True)
class ApplyProposalResult:
    proposal_id: str
    status: Literal["applied"]
    changed_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptProposalRequest:
    proposal_id: str


@dataclass(frozen=True, slots=True)
class AcceptProposalResult:
    proposal_id: str
    status: Literal["applied"]
    changed_paths: tuple[str, ...]
    completed_transitions: tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _map_lifecycle_error(e: TransitionError) -> Exception:
    if e.code in ("stale_proposal_source", "review_digest_mismatch", "invalid_transition"):
        return ToolConflictError("Conflict during transition")
    return ToolExecutionError("Execution failed during transition")


def _map_application_error(e: ApplicationError) -> Exception:
    if e.code is ApplicationErrorCode.RECOVERY_REQUIRED:
        return ToolRecoveryRequiredError("Recovery is required before application can continue")
    if e.code in (
        ApplicationErrorCode.TARGET_CONFLICT,
        ApplicationErrorCode.TARGET_MUTATED,
        ApplicationErrorCode.OWNERSHIP_CONFLICT,
    ):
        return ToolConflictError(f"Conflict during application: {e.message}")
    return ToolExecutionError(f"Execution failed during application: {e.message}")


def _load_proposal(proposal_id: str, proposals_root: Path) -> LoadedProposal:
    try:
        res = load_proposal_directory(
            proposals_root / proposal_id,
            proposals_root=proposals_root,
        )
    except OSError as e:
        raise ToolExecutionError("Could not load proposal") from e
    if res.proposal is None:
        # Check if missing
        if any(
            f.code in ("dir_open_failed", "root_open_failed", "not_immediate_child")
            for f in res.findings
        ):
            raise ToolNotFoundError(f"Proposal {proposal_id} not found")
        raise ToolExecutionError("Proposal is malformed or has load findings")
    return res.proposal


def submit_proposal_tool(
    *,
    vault_root: Path,
    request: SubmitProposalRequest,
    authorizer: ConsequentialAuthorizer,
    clock_fn: Callable[[], datetime] = _utc_now,
) -> SubmitProposalResult:
    proposals_root = vault_root / "proposals"
    proposal = _load_proposal(request.proposal_id, proposals_root)

    if proposal.metadata.status.value != "draft":
        raise ToolConflictError(f"Cannot submit from {proposal.metadata.status.value}")

    auth_req = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.SUBMIT,
        proposal_id=request.proposal_id,
        review_digest=None,
    )

    try:
        grant = authorizer.authorize(auth_req)
    except AuthorizationDeniedError as e:
        raise ToolAuthorizationError("Consequential operation was not authorized") from e
    except AuthorizationUnavailableError as e:
        raise ToolUnavailableError("Authorization service is unavailable") from e

    timestamp = _format_time(clock_fn())

    try:
        res = submit_proposal_for_review(
            proposal,
            proposals_root=proposals_root,
            submitted_by=grant.actor_id,
            submitted_at=timestamp,
        )
    except TransitionError as e:
        raise _map_lifecycle_error(e) from e

    # Reload to get the new digest from the written file
    reloaded = _load_proposal(request.proposal_id, proposals_root)
    digest = reloaded.metadata.review_digest or ""

    return SubmitProposalResult(
        proposal_id=res.proposal_id,
        status="pending",
        review_digest=digest,
    )


def approve_proposal_tool(
    *,
    vault_root: Path,
    request: ApproveProposalRequest,
    authorizer: ConsequentialAuthorizer,
    clock_fn: Callable[[], datetime] = _utc_now,
) -> ApproveProposalResult:
    proposals_root = vault_root / "proposals"
    proposal = _load_proposal(request.proposal_id, proposals_root)

    if proposal.metadata.status.value != "pending":
        raise ToolConflictError(f"Cannot approve from {proposal.metadata.status.value}")

    stored_digest = proposal.metadata.review_digest
    current_digest = compute_review_digest(
        proposal.metadata,
        proposal.body,
        proposal.patch_document,
        proposal.review_snapshot,
    )

    if not stored_digest:
        raise ToolConflictError("Stored review digest is missing")
    if current_digest != stored_digest:
        raise ToolConflictError("Current proposal content does not match stored review digest")

    auth_req = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.APPROVE,
        proposal_id=request.proposal_id,
        review_digest=current_digest,
    )

    try:
        grant = authorizer.authorize(auth_req)
    except AuthorizationDeniedError as e:
        raise ToolAuthorizationError("Consequential operation was not authorized") from e
    except AuthorizationUnavailableError as e:
        raise ToolUnavailableError("Authorization service is unavailable") from e

    timestamp = _format_time(clock_fn())

    try:
        res = approve_proposal(
            proposal,
            proposals_root=proposals_root,
            approved_by=grant.actor_id,
            approved_at=timestamp,
        )
    except TransitionError as e:
        raise _map_lifecycle_error(e) from e

    return ApproveProposalResult(
        proposal_id=res.proposal_id,
        status="approved",
        review_digest=current_digest,
    )


def apply_proposal_tool(
    *,
    vault_root: Path,
    request: ApplyProposalRequest,
    authorizer: ConsequentialAuthorizer,
    clock_fn: Callable[[], datetime] = _utc_now,
    identity_runtime_dir: Path | None = None,
) -> ApplyProposalResult:
    proposals_root = vault_root / "proposals"

    # 1. Validate and load proposal
    proposal = _load_proposal(request.proposal_id, proposals_root)

    # 2. Require approved status
    if proposal.metadata.status.value != "approved":
        raise ToolConflictError(f"Cannot apply from {proposal.metadata.status.value}")

    # 3. Compute canonical digest from currently loaded proposal
    current_digest = compute_review_digest(
        proposal.metadata,
        proposal.body,
        proposal.patch_document,
        proposal.review_snapshot,
    )

    # 4. Require stored review_digest is present
    stored_digest = proposal.metadata.review_digest
    if not stored_digest:
        raise ToolConflictError("Stored review digest is missing")

    # 5. Require current digest equals stored digest
    if current_digest != stored_digest:
        raise ToolConflictError("Current proposal content does not match stored review digest")

    # 6. Authorize APPLY separately with the exact current digest
    auth_req = ConsequentialAuthorizationRequest(
        action=ConsequentialAction.APPLY,
        proposal_id=request.proposal_id,
        review_digest=current_digest,
    )

    try:
        # 7. Obtain actor from AuthorizedPrincipal
        grant = authorizer.authorize(auth_req)
    except AuthorizationDeniedError as e:
        raise ToolAuthorizationError("Consequential operation was not authorized") from e
    except AuthorizationUnavailableError as e:
        raise ToolUnavailableError("Authorization service is unavailable") from e

    # 8. Call clock exactly once
    timestamp = _format_time(clock_fn())

    try:
        fresh_load_res = load_proposal_directory(
            proposals_root / request.proposal_id,
            proposals_root=proposals_root,
        )
    except OSError as e:
        raise ToolExecutionError("Could not reload proposal") from e

    if fresh_load_res.findings or fresh_load_res.proposal is None:
        raise ToolExecutionError("Proposal is malformed or has load findings")

    fresh_actual_digest = compute_review_digest(
        fresh_load_res.proposal.metadata,
        fresh_load_res.proposal.body,
        fresh_load_res.proposal.patch_document,
        fresh_load_res.proposal.review_snapshot,
    )
    if fresh_actual_digest != current_digest:
        raise ToolExecutionError("Proposal lock identity mismatch")

    try:
        # 9. Invoke apply_proposal with the fresh LoadedProposal
        res = apply_proposal(
            fresh_load_res.proposal,
            vault_root=vault_root,
            applied_by=grant.actor_id,
            applied_at=timestamp,
            identity_runtime_dir=identity_runtime_dir,
        )
    except ApplicationError as e:
        raise _map_application_error(e) from e

    # 10. Convert changed paths to vault-relative POSIX strings and return applied result
    return ApplyProposalResult(
        proposal_id=res.proposal_id,
        status="applied",
        changed_paths=tuple(Path(p).as_posix() for p in res.changed_paths),
    )


def accept_proposal_tool(
    *,
    vault_root: Path,
    request: AcceptProposalRequest,
    authorizer: ConsequentialAuthorizer,
    clock_fn: Callable[[], datetime] = _utc_now,
    identity_runtime_dir: Path | None = None,
) -> AcceptProposalResult:
    """Accept and apply one unchanged proposal with one exact UI authorization."""

    proposals_root = vault_root / "proposals"
    proposal = _load_proposal(request.proposal_id, proposals_root)
    if proposal.metadata.status.value not in ("draft", "pending", "approved"):
        raise ToolConflictError(
            f"Cannot accept from {proposal.metadata.status.value}"
        )

    accepted_digest = compute_review_digest(
        proposal.metadata,
        proposal.body,
        proposal.patch_document,
        proposal.review_snapshot,
    )
    if proposal.metadata.status.value != "draft":
        if proposal.metadata.review_digest != accepted_digest:
            raise ToolConflictError(
                "Current proposal content does not match stored review digest"
            )

    try:
        grant = authorizer.authorize(
            ConsequentialAuthorizationRequest(
                action=ConsequentialAction.APPLY,
                proposal_id=request.proposal_id,
                review_digest=accepted_digest,
            )
        )
    except AuthorizationDeniedError as exc:
        raise ToolAuthorizationError(
            "Consequential operation was not authorized"
        ) from exc
    except AuthorizationUnavailableError as exc:
        raise ToolUnavailableError(
            "Authorization service is unavailable"
        ) from exc

    timestamp = _format_time(clock_fn())
    completed: list[str] = []

    def reload_accepted() -> LoadedProposal:
        reloaded = _load_proposal(request.proposal_id, proposals_root)
        current_digest = compute_review_digest(
            reloaded.metadata,
            reloaded.body,
            reloaded.patch_document,
            reloaded.review_snapshot,
        )
        if current_digest != accepted_digest:
            raise ToolConflictError("Proposal changed after acceptance")
        if (
            reloaded.metadata.status.value != "draft"
            and reloaded.metadata.review_digest != accepted_digest
        ):
            raise ToolConflictError(
                "Stored review digest changed after acceptance"
            )
        return reloaded

    try:
        if proposal.metadata.status.value == "draft":
            submit_proposal_for_review(
                proposal,
                proposals_root=proposals_root,
                submitted_by=grant.actor_id,
                submitted_at=timestamp,
            )
            completed.append("submitted")
            proposal = reload_accepted()

        if proposal.metadata.status.value == "pending":
            approve_proposal(
                proposal,
                proposals_root=proposals_root,
                approved_by=grant.actor_id,
                approved_at=timestamp,
            )
            completed.append("approved")
            proposal = reload_accepted()
    except TransitionError as exc:
        raise _map_lifecycle_error(exc) from exc

    if proposal.metadata.status.value != "approved":
        raise ToolConflictError(
            f"Cannot apply accepted proposal from {proposal.metadata.status.value}"
        )

    try:
        result = apply_proposal(
            proposal,
            vault_root=vault_root,
            applied_by=grant.actor_id,
            applied_at=timestamp,
            identity_runtime_dir=identity_runtime_dir,
        )
    except ApplicationError as exc:
        raise _map_application_error(exc) from exc
    completed.append("applied")

    return AcceptProposalResult(
        proposal_id=result.proposal_id,
        status="applied",
        changed_paths=tuple(Path(path).as_posix() for path in result.changed_paths),
        completed_transitions=tuple(completed),
    )
