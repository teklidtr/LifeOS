"""Obsidian-facing proposal inspection and one-use authorization challenges."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lifeos.facade.authorization import AuthorizedPrincipal, ConsequentialAction, ConsequentialAuthorizationRequest, ConsequentialAuthorizer, AuthorizationDeniedError
from lifeos.facade.consequential_tools import ApplyProposalRequest, ApproveProposalRequest, SubmitProposalRequest, apply_proposal_tool, approve_proposal_tool, submit_proposal_tool
from lifeos.facade.errors import ToolFacadeError
from lifeos.proposals.lifecycle import compute_review_digest, reject_proposal
from lifeos.proposals.loader import load_proposal_directory

ProposalAction = Literal["submit", "approve", "apply", "reject"]


@dataclass(frozen=True, slots=True)
class ProposalInspection:
    proposal_id: str
    status: str
    title: str
    description: str
    body: str
    review_digest: str
    operations: tuple[dict[str, Any], ...]
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

    def inspect(self, proposal_id: str) -> ProposalInspection:
        root = self.vault_root / "proposals"
        loaded = load_proposal_directory(root / proposal_id, proposals_root=root)
        if loaded.proposal is None:
            raise ValueError("Proposal is missing or malformed")
        proposal = loaded.proposal
        digest = compute_review_digest(proposal.metadata, proposal.body, proposal.patch_document)
        operations = tuple(
            {
                key: value
                for key, value in vars(operation).items()
                if not key.startswith("_")
            }
            for operation in proposal.patch_document.operations
        )
        return ProposalInspection(
            proposal_id,
            proposal.metadata.status.value,
            proposal.metadata.title,
            proposal.metadata.description,
            proposal.body,
            digest,
            operations,
            proposal.metadata.related_sources,
            tuple(f"{finding.code}: {finding.message}" for finding in loaded.findings),
        )

    def prepare(self, *, proposal_id: str, action: ProposalAction) -> ConfirmationChallenge:
        inspection = self.inspect(proposal_id)
        action_enum = {
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
