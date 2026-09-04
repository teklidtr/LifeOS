from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.facade.errors import ToolConflictError, ToolNotFoundError, ToolValidationError
from lifeos.facade.personal_pattern_tools import (
    AgentPatternSemanticInput,
    ObservedPatternEvidence,
    ProposeAgentPatternRequest,
    ReviewAgentPatternRequest,
    propose_agent_pattern,
    review_agent_pattern,
)
from lifeos.patterns import (
    PatternArtifactService,
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.patterns.agent_assistance import (
    PatternAssistanceEvidence,
    PatternAssistanceRequest,
    PatternSemanticSuggestion,
    assist_pattern,
)
from lifeos.proposals import CreateFile, PatchHumanFile, load_proposal_directory
from lifeos.registry.file_tracking import hash_file_content
from lifeos.retrieval import ProviderCapabilities, ProviderError


def _write_source(vault: Path, path: str, body: str, *, source_id: str | None = None) -> str:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = ""
    if source_id is not None:
        frontmatter = f"---\nid: {source_id}\n---\n"
    content = (frontmatter + body).encode("utf-8")
    target.write_bytes(content)
    return f"sha256:{hash_file_content(content)}"


def _observed(path: str, content_hash: str, role: str = "supporting") -> ObservedPatternEvidence:
    return ObservedPatternEvidence(path=path, content_hash=content_hash, role=role)  # type: ignore[arg-type]


def _semantic(hypothesis: str = "Walking before study may improve focus.") -> AgentPatternSemanticInput:
    return AgentPatternSemanticInput(
        hypothesis=hypothesis,
        rationale="The selected journal entries repeatedly place walking before focused sessions.",
        proposed_confidence="low",
        competing_explanations=("The effect may instead reflect time of day.",),
        limitations=("Only a small number of self-recorded observations were selected.",),
    )


def _load_proposal(vault: Path, proposal_id: str):
    result = load_proposal_directory(
        vault / "proposals" / proposal_id,
        proposals_root=vault / "proposals",
    )
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


def _write_pattern(vault: Path, evidence: tuple[PatternEvidence, ...]) -> Path:
    target = vault / "patterns" / "focus-after-walk.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = PatternMetadata(
        pattern_id="pattern-focus-after-walk",
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
    return target


def _provider_evidence(text: str = "Walked, then completed a focused study block."):
    return PatternAssistanceEvidence(
        reference=PatternEvidence(
            path="journal/source.md",
            content_hash="sha256:" + "a" * 64,
            role="supporting",
        ),
        text=text,
    )


def test_new_agent_pattern_is_exact_evidence_bound_draft_with_counter_evidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    support_hash = _write_source(
        vault,
        "journal/support.md",
        "Walked, then completed a focused study block.\n",
        source_id="journal-support",
    )
    contest_hash = _write_source(
        vault,
        "journal/contest.md",
        "Walked, but focus stayed low.\n",
        source_id="journal-contest",
    )

    result = propose_agent_pattern(
        vault_root=vault,
        request=ProposeAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            pattern_id="pattern-focus-after-walk",
            title="Focus after walking",
            description="Walking before study may be associated with better focus.",
            semantic=_semantic(),
            evidence=(
                _observed("journal/support.md", support_hash),
                _observed("journal/contest.md", contest_hash, "contesting"),
            ),
        ),
    )

    assert result.state == "draft"
    assert result.proposal_id is not None
    assert not (vault / "patterns" / "focus-after-walk.md").exists()
    proposal = _load_proposal(vault, result.proposal_id)
    operation = proposal.patch_document.operations[0]
    assert isinstance(operation, CreateFile)
    assert operation.target_path == "patterns/focus-after-walk.md"
    review = proposal.metadata.extensions["personal_pattern"]["agent_assistance"]
    assert review["authority"] == "proposal-only"
    assert review["hidden_reasoning_stored"] is False
    assert review["proposed_confidence"] == "low"
    assert review["supporting_evidence"][0]["path"] == "journal/support.md"
    assert review["supporting_evidence"][0]["content_hash"] == support_hash
    assert review["contesting_evidence"][0]["path"] == "journal/contest.md"
    assert "time of day" in review["competing_explanations"][0]
    assert "No hidden chain-of-thought is stored" in proposal.body


def test_changed_missing_and_protected_evidence_fail_before_draft_publication(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    observed_hash = _write_source(vault, "journal/source.md", "First version.\n")
    (vault / "journal" / "source.md").write_text("Changed version.\n", encoding="utf-8")

    base = dict(
        target_path="patterns/test.md",
        pattern_id="pattern-test",
        title="Test hypothesis",
        description="A bounded test hypothesis.",
        semantic=_semantic(),
    )
    with pytest.raises(ToolConflictError):
        propose_agent_pattern(
            vault_root=vault,
            request=ProposeAgentPatternRequest(
                **base,
                evidence=(_observed("journal/source.md", observed_hash),),
            ),
        )

    with pytest.raises(ToolNotFoundError):
        propose_agent_pattern(
            vault_root=vault,
            request=ProposeAgentPatternRequest(
                **base,
                evidence=(_observed("journal/missing.md", "sha256:" + "a" * 64),),
            ),
        )

    private_hash = _write_source(vault, "private/evidence.md", "Private evidence.\n")
    with pytest.raises(ToolValidationError):
        propose_agent_pattern(
            vault_root=vault,
            request=ProposeAgentPatternRequest(
                **base,
                evidence=(_observed("private/evidence.md", private_hash),),
            ),
        )
    assert not (vault / "proposals").exists()


def test_existing_pattern_review_can_return_zero_change_or_a_hash_bound_revision(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    support_hash = _write_source(
        vault,
        "journal/support.md",
        "Walked, then focused.\n",
        source_id="journal-support",
    )
    support = PatternEvidence(
        path="journal/support.md",
        content_hash=support_hash,
        role="supporting",
        source_id="journal-support",
    )
    target = _write_pattern(vault, (support,))
    current = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")

    no_change = review_agent_pattern(
        vault_root=vault,
        request=ReviewAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            observed_pattern_hash=current.content_hash,
            semantic=_semantic(),
            evidence=(_observed("journal/support.md", support_hash),),
        ),
    )
    assert no_change.state == "no-change"
    assert no_change.proposal_id is None
    assert not (vault / "proposals").exists()

    contest_hash = _write_source(vault, "journal/contest.md", "Walked, focus remained low.\n")
    before = target.read_bytes()
    revision = review_agent_pattern(
        vault_root=vault,
        request=ReviewAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            observed_pattern_hash=current.content_hash,
            semantic=_semantic("Walking may help focus only in some contexts."),
            evidence=(
                _observed("journal/support.md", support_hash),
                _observed("journal/contest.md", contest_hash, "contesting"),
            ),
        ),
    )
    assert revision.state == "draft"
    assert revision.proposal_id is not None
    proposal = _load_proposal(vault, revision.proposal_id)
    assert isinstance(proposal.patch_document.operations[0], PatchHumanFile)
    assert target.read_bytes() == before

    target.write_text(target.read_text(encoding="utf-8") + "\nHuman edit.\n", encoding="utf-8")
    with pytest.raises(ToolConflictError):
        review_agent_pattern(
            vault_root=vault,
            request=ReviewAgentPatternRequest(
                target_path="patterns/focus-after-walk.md",
                observed_pattern_hash=current.content_hash,
                semantic=_semantic("A different revision."),
                evidence=(_observed("journal/support.md", support_hash),),
            ),
        )


class _TimeoutProvider:
    capabilities = ProviderCapabilities(
        kind="generation",
        adapter_key="test-timeout",
        model_key="test-model",
        local_only=True,
        max_batch_size=1,
    )

    def suggest(self, request, *, timeout_seconds, cancellation):
        raise ProviderError("timeout", "provider timed out")


class _MalformedProvider:
    capabilities = ProviderCapabilities(
        kind="generation",
        adapter_key="test-malformed",
        model_key="test-model",
        local_only=True,
        max_batch_size=1,
    )

    def suggest(self, request, *, timeout_seconds, cancellation):
        return {"hypothesis": "not a typed suggestion"}


class _ZeroProvider:
    capabilities = ProviderCapabilities(
        kind="generation",
        adapter_key="test-zero",
        model_key="test-model",
        local_only=True,
        max_batch_size=1,
    )

    def suggest(self, request, *, timeout_seconds, cancellation):
        return None


def test_optional_provider_failures_do_not_create_semantic_authority() -> None:
    request = PatternAssistanceRequest(
        purpose="new-pattern",
        evidence=(_provider_evidence(),),
    )

    assert assist_pattern(request, provider=None).state == "no-model"
    assert assist_pattern(request, provider=_ZeroProvider()).state == "no-proposal"
    assert assist_pattern(request, provider=_TimeoutProvider()).state == "timeout"
    malformed = assist_pattern(request, provider=_MalformedProvider())
    assert malformed.state == "malformed-output"
    assert malformed.suggestion is None


def test_typed_provider_receives_only_bounded_selected_evidence() -> None:
    seen = {}

    class Provider:
        capabilities = ProviderCapabilities(
            kind="generation",
            adapter_key="test-ready",
            model_key="test-model",
            local_only=True,
            max_batch_size=1,
        )

        def suggest(self, request, *, timeout_seconds, cancellation):
            seen["path"] = request.evidence[0].reference.path
            seen["text"] = request.evidence[0].text
            return PatternSemanticSuggestion(
                hypothesis="A cautious hypothesis.",
                rationale="Selected evidence supports review.",
                competing_explanations=(),
                limitations=("Small sample.",),
                proposed_confidence="low",
            )

    evidence_text = "Walked, then completed a focused study block."
    request = PatternAssistanceRequest(
        purpose="new-pattern",
        evidence=(_provider_evidence(evidence_text),),
    )
    result = assist_pattern(request, provider=Provider())

    assert result.state == "ready"
    assert result.suggestion is not None
    assert result.suggestion.hypothesis == "A cautious hypothesis."
    assert seen == {"path": "journal/source.md", "text": evidence_text}
    assert result.provider_disclosure["sent_paths"] == ["journal/source.md"]
    assert result.provider_disclosure["character_count"] == len(evidence_text)


def test_provider_batch_and_total_evidence_budget_fail_closed() -> None:
    class Provider:
        capabilities = ProviderCapabilities(
            kind="generation",
            adapter_key="test-small-batch",
            model_key="test-model",
            local_only=True,
            max_batch_size=1,
        )

        def suggest(self, request, *, timeout_seconds, cancellation):
            raise AssertionError("provider must not receive an oversized batch")

    batch = PatternAssistanceRequest(
        purpose="new-pattern",
        evidence=(_provider_evidence("one"), _provider_evidence("two")),
    )
    assert assist_pattern(batch, provider=Provider()).state == "provider-unavailable"

    with pytest.raises(ValueError, match="disclosure budget"):
        PatternAssistanceRequest(
            purpose="new-pattern",
            evidence=(_provider_evidence("x" * 24_001),),
        )
