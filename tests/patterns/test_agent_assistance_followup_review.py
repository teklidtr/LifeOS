from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.facade.authorization import (
    AuthorizedPrincipal,
    ConsequentialAction,
    ConsequentialAuthorizationRequest,
)
from lifeos.facade.consequential_tools import (
    AcceptProposalRequest,
    ApplyProposalRequest,
    accept_proposal_tool,
    apply_proposal_tool,
)
from lifeos.facade.errors import ToolConflictError
from lifeos.facade.personal_pattern_tools import (
    AgentPatternSemanticInput,
    ObservedPatternEvidence,
    ProposeAgentPatternRequest,
    propose_agent_pattern,
)
from lifeos.patterns import (
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.patterns.artifact import parse_pattern
from lifeos.proposals import (
    ApplicationError,
    CreateFile,
    apply_proposal,
    load_proposal_directory,
)
from lifeos.proposals.application import ApplicationErrorCode
from lifeos.proposals.lifecycle import approve_proposal, submit_proposal_for_review
from lifeos.registry.file_tracking import hash_file_content


def _write_source(vault: Path, path: str, body: str) -> str:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    content = body.encode("utf-8")
    target.write_bytes(content)
    return f"sha256:{hash_file_content(content)}"


def _write_pattern(
    vault: Path,
    path: str,
    *,
    pattern_id: str,
    evidence: tuple[PatternEvidence, ...],
) -> None:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = PatternMetadata(
        pattern_id=pattern_id,
        title="Focus after walking",
        description="Walking before study may be associated with better focus.",
        status="seed",
        confidence="low",
        review_reasons=(),
        statement="Walking before study may improve focus.",
        origin=PatternOrigin("agent"),
        created_at="2026-09-04T08:00:00Z",
        updated_at="2026-09-04T08:00:00Z",
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
    )
    target.write_text(serialize_pattern(metadata), encoding="utf-8")


def _write_pattern_policy(vault: Path) -> None:
    system = vault / "system"
    system.mkdir(parents=True, exist_ok=True)
    (system / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "protected_prefixes:\n"
        "  - patterns/private\n"
        "external_allowed_prefixes: []\n",
        encoding="utf-8",
    )


def _write_empty_ownership(vault: Path) -> None:
    system = vault / "system"
    system.mkdir(parents=True, exist_ok=True)
    (system / "generated-ownership.json").write_text(
        '{"schema_version":1,"owned_files":{}}\n',
        encoding="utf-8",
    )


def _observed(source_hash: str) -> tuple[ObservedPatternEvidence, ...]:
    return (
        ObservedPatternEvidence(
            path="journal/source.md",
            content_hash=source_hash,
            role="supporting",
        ),
    )


def _semantic(hypothesis: str) -> AgentPatternSemanticInput:
    return AgentPatternSemanticInput(
        hypothesis=hypothesis,
        rationale="The selected evidence supports cautious review.",
        proposed_confidence="low",
    )


def _load(vault: Path, proposal_id: str):
    loaded = load_proposal_directory(
        vault / "proposals" / proposal_id,
        proposals_root=vault / "proposals",
    )
    assert loaded.findings == ()
    assert loaded.proposal is not None
    return loaded.proposal


def _approve(vault: Path, proposal_id: str, *, minute: int) -> None:
    proposal = _load(vault, proposal_id)
    submit_proposal_for_review(
        proposal,
        proposals_root=vault / "proposals",
        submitted_by="trusted-human",
        submitted_at=f"2026-09-04T20:{minute:02d}:00Z",
    )
    pending = _load(vault, proposal_id)
    approve_proposal(
        pending,
        proposals_root=vault / "proposals",
        approved_by="trusted-human",
        approved_at=f"2026-09-04T20:{minute + 1:02d}:00Z",
    )


def _create_seed_draft(
    vault: Path,
    *,
    target_path: str,
    pattern_id: str,
    source_hash: str,
) -> str:
    draft = propose_agent_pattern(
        vault_root=vault,
        request=ProposeAgentPatternRequest(
            target_path=target_path,
            pattern_id=pattern_id,
            title="Focus after walking",
            description="Walking before study may be associated with better focus.",
            semantic=_semantic("Walking before study may improve focus."),
            evidence=_observed(source_hash),
        ),
    )
    assert draft.state == "draft"
    assert draft.proposal_id is not None
    return draft.proposal_id


def _hidden_collision_draft(vault: Path) -> str:
    source_hash = _write_source(vault, "journal/source.md", "Walked, then focused.\n")
    evidence = (
        PatternEvidence(
            path="journal/source.md",
            content_hash=source_hash,
            role="supporting",
        ),
    )
    _write_pattern(
        vault,
        "patterns/private/hidden.md",
        pattern_id="pattern-focus-after-walk",
        evidence=evidence,
    )
    _write_pattern_policy(vault)
    _write_empty_ownership(vault)
    return _create_seed_draft(
        vault,
        target_path="patterns/focus-after-walk.md",
        pattern_id="pattern-focus-after-walk",
        source_hash=source_hash,
    )


class _ApplyAuthorizer:
    def __init__(self) -> None:
        self.requests: list[ConsequentialAuthorizationRequest] = []

    def authorize(self, request: ConsequentialAuthorizationRequest, /) -> AuthorizedPrincipal:
        self.requests.append(request)
        return AuthorizedPrincipal("trusted-human")


def test_hidden_pattern_id_collision_is_blocked_only_at_trusted_apply(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposal_id = _hidden_collision_draft(vault)
    _approve(vault, proposal_id, minute=0)

    authorizer = _ApplyAuthorizer()
    with pytest.raises(ToolConflictError, match="pattern identity is not unique"):
        apply_proposal_tool(
            vault_root=vault,
            request=ApplyProposalRequest(proposal_id),
            authorizer=authorizer,
            clock_fn=lambda: datetime(2026, 9, 4, 20, 2, tzinfo=timezone.utc),
        )

    assert [request.action for request in authorizer.requests] == [ConsequentialAction.APPLY]
    assert not (vault / "patterns" / "focus-after-walk.md").exists()
    assert (vault / "patterns" / "private" / "hidden.md").exists()


def test_composite_accept_uses_the_same_trusted_pattern_identity_guard(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    proposal_id = _hidden_collision_draft(vault)
    authorizer = _ApplyAuthorizer()

    with pytest.raises(ToolConflictError, match="pattern identity is not unique"):
        accept_proposal_tool(
            vault_root=vault,
            request=AcceptProposalRequest(proposal_id),
            authorizer=authorizer,
            clock_fn=lambda: datetime(2026, 9, 4, 20, 2, tzinfo=timezone.utc),
        )

    assert [request.action for request in authorizer.requests] == [ConsequentialAction.APPLY]
    assert _load(vault, proposal_id).metadata.status.value == "approved"
    assert not (vault / "patterns" / "focus-after-walk.md").exists()


def test_application_rechecks_identity_after_another_approved_seed_is_applied(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    source_hash = _write_source(vault, "journal/source.md", "Walked, then focused.\n")
    (vault / "patterns").mkdir(parents=True, exist_ok=True)
    _write_empty_ownership(vault)

    first_id = _create_seed_draft(
        vault,
        target_path="patterns/focus-after-walk-a.md",
        pattern_id="pattern-focus-after-walk",
        source_hash=source_hash,
    )
    second_id = _create_seed_draft(
        vault,
        target_path="patterns/focus-after-walk-b.md",
        pattern_id="pattern-focus-after-walk",
        source_hash=source_hash,
    )
    _approve(vault, first_id, minute=10)
    _approve(vault, second_id, minute=20)

    # Both approved proposal snapshots are loaded before either canonical mutation. This models
    # two calls that both passed every pre-application check before mutation serialization.
    first = _load(vault, first_id)
    second = _load(vault, second_id)

    applied = apply_proposal(
        first,
        vault_root=vault,
        applied_by="trusted-human",
        applied_at="2026-09-04T21:00:00Z",
    )
    assert applied.new_status.value == "applied"
    assert (vault / "patterns" / "focus-after-walk-a.md").exists()

    with pytest.raises(ApplicationError) as raised:
        apply_proposal(
            second,
            vault_root=vault,
            applied_by="trusted-human",
            applied_at="2026-09-04T21:01:00Z",
        )

    assert raised.value.code is ApplicationErrorCode.PREFLIGHT_FAILED
    assert "Canonical personal-pattern identity already exists." in raised.value.message
    assert not (vault / "patterns" / "focus-after-walk-b.md").exists()


def test_create_uses_normalized_hypothesis_for_review_and_canonical_candidate(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    source_hash = _write_source(vault, "journal/source.md", "Walked, then focused.\n")

    result = propose_agent_pattern(
        vault_root=vault,
        request=ProposeAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            pattern_id="pattern-focus-after-walk",
            title="Focus after walking",
            description="Walking before study may be associated with better focus.",
            semantic=_semantic("Walking   before\nstudy may improve focus."),
            evidence=_observed(source_hash),
        ),
    )
    assert result.proposal_id is not None
    proposal = _load(vault, result.proposal_id)
    operation = proposal.patch_document.operations[0]
    assert isinstance(operation, CreateFile)
    artifact = parse_pattern(
        vault / "patterns" / "focus-after-walk.md",
        "patterns/focus-after-walk.md",
        operation.new_content,
    )
    assert artifact is not None
    assert artifact.metadata.statement == "Walking before study may improve focus."
    review = proposal.metadata.extensions["personal_pattern"]["agent_assistance"]
    assert review["hypothesis"] == artifact.metadata.statement
