"""Interactive TTY-based authorizer for MCP consequential operations."""

from __future__ import annotations

import io
from pathlib import Path

from lifeos.facade.authorization import (
    AuthorizationDeniedError,
    AuthorizationUnavailableError,
    AuthorizedPrincipal,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
    ConsequentialAuthorizer,
)
from lifeos.proposals.lifecycle import compute_review_digest
from lifeos.proposals.loader import LoadedProposal, load_proposal_directory
from lifeos.proposals.schema import ProposalSchemaError, validate_proposal_id


class InteractiveTtyAuthorizer(ConsequentialAuthorizer):
    def __init__(self, vault_root: Path, actor_id: str) -> None:
        self.vault_root = vault_root
        self.actor_id = actor_id

    def authorize(self, request: ConsequentialAuthorizationRequest) -> AuthorizedPrincipal:
        try:
            validate_proposal_id(request.proposal_id)
        except ProposalSchemaError as error:
            raise AuthorizationUnavailableError(
                "Proposal could not be loaded for authorization"
            ) from error

        proposal_dir = self.vault_root / "proposals" / request.proposal_id
        proposals_root = self.vault_root / "proposals"

        load_result = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
        if load_result.findings or load_result.proposal is None:
            raise AuthorizationUnavailableError("Proposal could not be loaded for authorization")

        proposal = load_result.proposal

        current_digest = compute_review_digest(
            proposal.metadata,
            proposal.body,
            proposal.patch_document,
            proposal.review_snapshot,
        )

        if request.action in {ConsequentialAction.APPROVE, ConsequentialAction.APPLY}:
            if request.review_digest is None:
                raise AuthorizationDeniedError("Consequential operation was not authorized")
            if current_digest != request.review_digest:
                raise AuthorizationDeniedError("Consequential operation was not authorized")
        elif request.action is ConsequentialAction.SUBMIT:
            if request.review_digest is not None:
                raise AuthorizationDeniedError("Consequential operation was not authorized")

        try:
            with open("/dev/tty", "r+", encoding="utf-8", buffering=1) as tty:
                self._render_review(tty, request, proposal, current_digest)
                response = tty.readline()
        except OSError as error:
            raise AuthorizationUnavailableError("Interactive authorization is unavailable") from error

        if response.strip().lower() != "y":
            raise AuthorizationDeniedError("Consequential operation was not authorized")

        return AuthorizedPrincipal(actor_id=self.actor_id)

    def _render_review(
        self,
        tty: io.TextIOWrapper,
        request: ConsequentialAuthorizationRequest,
        proposal: LoadedProposal,
        current_digest: str,
    ) -> None:
        tty.write("\n=== LifeOS Consequential Authorization ===\n")
        tty.write(f"Action:      {request.action.name}\n")
        tty.write(f"Proposal ID: {request.proposal_id}\n")
        tty.write(f"Title:       {proposal.metadata.title}\n")
        tty.write(f"Description: {proposal.metadata.description}\n")
        tty.write(f"\n--- Body ---\n{proposal.body}\n")
        
        # Format patches nicely
        tty.write("\n--- Patches ---\n")
        operations = getattr(proposal.patch_document, "operations", [])
        if not operations:
            tty.write("No patch operations.\n")
            
        for patch in operations:
            tty.write(f"\nOperation ID: {patch.id}\n")
            tty.write(f"Type:         {patch.op}\n")
            tty.write(f"Target Path:  {patch.target_path}\n")
            
            if patch.op == "replace_managed_block":
                tty.write(f"Block Name:   {patch.block_name}\n")
                tty.write(f"Expected:     {patch.base_hash}\n")
                tty.write(f"New Content:\n{patch.new_content}\n")
            elif patch.op == "create_generated_file":
                tty.write(f"Generator ID: {patch.generator_id}\n")
                if hasattr(patch, "generator_version"):
                    tty.write(f"Version:      {patch.generator_version}\n")
                tty.write(f"Expected:     {patch.expected_target_state}\n")
                tty.write(f"New Content:\n{patch.new_content}\n")
            elif patch.op == "replace_generated_file":
                tty.write(f"Generator ID: {patch.expected_generator_id}\n")
                if hasattr(patch, "generator_version"):
                    tty.write(f"Version:      {patch.generator_version}\n")
                tty.write(f"Expected:     {patch.base_hash}\n")
                tty.write(f"New Content:\n{patch.new_content}\n")
            elif patch.op == "create_file":
                tty.write(f"Expected:     {patch.expected_target_state}\n")
                tty.write(f"New Content:\n{patch.new_content}\n")
            elif patch.op == "patch_human_file":
                tty.write(f"Expected:     {patch.base_hash}\n")
                tty.write(f"Unified Diff:\n{patch.unified_diff}\n")
            else:
                raise AuthorizationUnavailableError(
                    "Proposal could not be rendered for authorization"
                )

            
        if request.action in {ConsequentialAction.APPROVE, ConsequentialAction.APPLY}:
            tty.write(f"\nVerified Digest: {current_digest}\n")
        else:
            tty.write(f"\nComputed Digest: {current_digest}\n")
        tty.write("\nAllow this operation? (y/N): ")
        tty.flush()
