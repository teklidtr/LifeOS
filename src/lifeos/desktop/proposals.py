"""Obsidian-facing proposal inspection and one-use authorization challenges."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lifeos.facade.authorization import AuthorizedPrincipal, ConsequentialAction, ConsequentialAuthorizationRequest, ConsequentialAuthorizer, AuthorizationDeniedError
from lifeos.facade.consequential_tools import AcceptProposalRequest, ApplyProposalRequest, ApproveProposalRequest, SubmitProposalRequest, accept_proposal_tool, apply_proposal_tool, approve_proposal_tool, submit_proposal_tool
from lifeos.facade.errors import ToolFacadeError
from lifeos.proposals.lifecycle import compute_review_digest, reject_proposal
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.review_snapshot import (
    OperationReviewSnapshot,
    ReviewSnapshotError,
    operation_unified_diff,
)
from lifeos.ownership import (
    create_ownership_release_proposal,
    list_orphaned_generated_ownership,
)

ProposalAction = Literal["accept", "submit", "approve", "apply", "reject"]


@dataclass(frozen=True, slots=True)
class ProposalOperationInspection:
    operation_id: str
    operation_type: str
    target_path: str
    unified_diff: str
    preview_error: str | None = None
    preview_source: Literal["snapshot", "legacy_live"] = "legacy_live"


@dataclass(frozen=True, slots=True)
class ProposalInspection:
    proposal_id: str
    status: str
    title: str
    created_at: str
    description: str
    body: str
    review_digest: str
    operations: tuple[ProposalOperationInspection, ...]
    related_sources: tuple[str, ...]
    findings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConfirmationChallenge:
    token: str
    proposal_id: str
    action: ProposalAction
    review_digest: str
    expires_at: str


class OneUseUiAuthorizer(ConsequentialAuthorizer):
    def __init__(self, actor_id: str) -> None:
        self.actor_id = actor_id
        self._grants: dict[str, tuple[ConsequentialAction, str, str | None]] = {}
        self._active_token: str | None = None

    def issue(self, *, action: ConsequentialAction, proposal_id: str, review_digest: str | None) -> str:
        token = secrets.token_urlsafe(24)
        self._grants[token] = (action, proposal_id, review_digest)
        return token

    def activate(self, token: str) -> None:
        if token not in self._grants:
            raise AuthorizationDeniedError("Confirmation token is invalid or already used")
        self._active_token = token

    def authorize(self, request: ConsequentialAuthorizationRequest, /) -> AuthorizedPrincipal:
        token = self._active_token
        self._active_token = None
        if token is None:
            raise AuthorizationDeniedError("No trusted UI confirmation is active")
        expected = self._grants.pop(token, None)
        if expected != (request.action, request.proposal_id, request.review_digest):
            raise AuthorizationDeniedError("Confirmation does not match the exact proposal content")
        return AuthorizedPrincipal(self.actor_id)


class DesktopProposalService:
    def __init__(self, *, vault_root: Path, actor_id: str) -> None:
        self.vault_root = vault_root
        self.actor_id = actor_id
        self.authorizer = OneUseUiAuthorizer(actor_id)

    def list(self) -> tuple[ProposalInspection, ...]:
        root = self.vault_root / "proposals"
        if not root.exists():
            return ()
        results = []
        for child in sorted(root.iterdir(), key=lambda path: path.name):
            if child.is_dir():
                try:
                    results.append(self.inspect(child.name))
                except ValueError:
                    continue
        return tuple(results)

    def list_orphaned_ownership(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            orphan.to_dict()
            for orphan in list_orphaned_generated_ownership(self.vault_root)
        )

    def create_ownership_release_proposal(self, target_path: str) -> dict[str, str]:
        return create_ownership_release_proposal(
            vault_root=self.vault_root,
            target_path=target_path,
            created_by=self.actor_id,
        ).to_dict()

    def inspect(self, proposal_id: str) -> ProposalInspection:
        root = self.vault_root / "proposals"
        loaded = load_proposal_directory(root / proposal_id, proposals_root=root)
        if loaded.proposal is None:
            raise ValueError("Proposal is missing or malformed")
        proposal = loaded.proposal
        digest = compute_review_digest(
            proposal.metadata,
            proposal.body,
            proposal.patch_document,
            proposal.review_snapshot,
        )
        snapshot_operations = (
            proposal.review_snapshot.operations
            if proposal.review_snapshot is not None
            else (None,) * len(proposal.patch_document.operations)
        )
        operations = tuple(
            self._inspect_operation(operation, snapshot_operation)
            for operation, snapshot_operation in zip(
                proposal.patch_document.operations,
                snapshot_operations,
                strict=True,
            )
        )
        findings = [
            f"{finding.code}: {finding.message}" for finding in loaded.findings
        ]
        if proposal.review_snapshot is None:
            findings.append(
                "legacy_review_snapshot_missing: diff preview is reconstructed from current vault state"
            )
        return ProposalInspection(
            proposal_id=proposal_id,
            status=proposal.metadata.status.value,
            title=proposal.metadata.title,
            created_at=proposal.metadata.created_at,
            description=proposal.metadata.description,
            body=proposal.body,
            review_digest=digest,
            operations=operations,
            related_sources=proposal.metadata.related_sources,
            findings=tuple(findings),
        )

    def _inspect_operation(
        self,
        operation: Any,
        snapshot_operation: OperationReviewSnapshot | None,
    ) -> ProposalOperationInspection:
        target_path = operation.target_path
        if snapshot_operation is not None:
            return ProposalOperationInspection(
                operation_id=operation.id,
                operation_type=operation.op,
                target_path=target_path,
                unified_diff=snapshot_operation.unified_diff,
                preview_source="snapshot",
            )
        try:
            unified_diff = operation_unified_diff(self.vault_root, operation)
            preview_error = None
        except ReviewSnapshotError as exc:
            unified_diff = ""
            message = exc.message
            if exc.code == "stale_base_hash":
                message = "target content no longer matches the proposal base hash"
            preview_error = f"Diff preview unavailable: {message}"
        except (OSError, UnicodeError, ValueError) as exc:
            unified_diff = ""
            preview_error = f"Diff preview unavailable: {exc}"
        return ProposalOperationInspection(
            operation_id=operation.id,
            operation_type=operation.op,
            target_path=target_path,
            unified_diff=unified_diff,
            preview_error=preview_error,
            preview_source="legacy_live",
        )

    def prepare(self, *, proposal_id: str, action: ProposalAction) -> ConfirmationChallenge:
        inspection = self.inspect(proposal_id)
        if action == "accept" and inspection.status not in ("draft", "pending", "approved"):
            raise ValueError(f"Cannot accept a {inspection.status} proposal")
        action_enum = {
            "accept": ConsequentialAction.APPLY,
            "submit": ConsequentialAction.SUBMIT,
            "approve": ConsequentialAction.APPROVE,
            "apply": ConsequentialAction.APPLY,
            "reject": ConsequentialAction.APPROVE,
        }[action]
        digest = None if action == "submit" else inspection.review_digest
        token = self.authorizer.issue(action=action_enum, proposal_id=proposal_id, review_digest=digest)
        return ConfirmationChallenge(token, proposal_id, action, inspection.review_digest, datetime.now(timezone.utc).isoformat())

    def execute(self, *, proposal_id: str, action: ProposalAction, token: str, reason: str | None = None) -> dict[str, Any]:
        self.authorizer.activate(token)
        try:
            if action == "accept":
                return asdict(accept_proposal_tool(vault_root=self.vault_root, request=AcceptProposalRequest(proposal_id), authorizer=self.authorizer))
            if action == "submit":
                return asdict(submit_proposal_tool(vault_root=self.vault_root, request=SubmitProposalRequest(proposal_id), authorizer=self.authorizer))
            if action == "approve":
                return asdict(approve_proposal_tool(vault_root=self.vault_root, request=ApproveProposalRequest(proposal_id), authorizer=self.authorizer))
            if action == "apply":
                return asdict(apply_proposal_tool(vault_root=self.vault_root, request=ApplyProposalRequest(proposal_id), authorizer=self.authorizer))
            if action == "reject":
                inspection = self.inspect(proposal_id)
                request = ConsequentialAuthorizationRequest(ConsequentialAction.APPROVE, proposal_id, inspection.review_digest)
                grant = self.authorizer.authorize(request)
                loaded = load_proposal_directory(self.vault_root / "proposals" / proposal_id, proposals_root=self.vault_root / "proposals")
                if loaded.proposal is None:
                    raise ValueError("Proposal is missing")
                result = reject_proposal(
                    loaded.proposal,
                    proposals_root=self.vault_root / "proposals",
                    rejected_by=grant.actor_id,
                    rejected_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    rejection_reason=(reason or "Rejected in Obsidian").strip(),
                )
                return {"proposal_id": result.proposal_id, "status": "rejected"}
        except ToolFacadeError as exc:
            raise ValueError(str(exc)) from exc
        raise ValueError("Unsupported proposal action")
