from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.facade.errors import ToolValidationError
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
from lifeos.registry.file_tracking import hash_file_content


def _write_source(vault: Path, path: str, body: str) -> str:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    content = body.encode("utf-8")
    target.write_bytes(content)
    return f"sha256:{hash_file_content(content)}"


def _semantic() -> AgentPatternSemanticInput:
    return AgentPatternSemanticInput(
        hypothesis="Walking before study may improve focus.",
        rationale="The selected evidence supports cautious review.",
        proposed_confidence="low",
    )


def _pattern_metadata(
    pattern_id: str,
    evidence: tuple[PatternEvidence, ...],
) -> PatternMetadata:
    return PatternMetadata(
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


def _write_pattern(
    vault: Path,
    path: str,
    *,
    pattern_id: str,
    evidence: tuple[PatternEvidence, ...],
) -> Path:
    target = vault / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        serialize_pattern(_pattern_metadata(pattern_id, evidence)),
        encoding="utf-8",
    )
    return target


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


def test_create_rejects_protected_target_before_target_state_can_leak(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
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
        "patterns/private/existing.md",
        pattern_id="pattern-private",
        evidence=evidence,
    )
    _write_pattern_policy(vault)

    with pytest.raises(ToolValidationError):
        propose_agent_pattern(
            vault_root=vault,
            request=ProposeAgentPatternRequest(
                target_path="patterns/private/existing.md",
                pattern_id="pattern-private",
                title="Private pattern",
                description="Protected target state must not cross the external boundary.",
                semantic=_semantic(),
                evidence=(
                    ObservedPatternEvidence(
                        path="journal/source.md",
                        content_hash=source_hash,
                        role="supporting",
                    ),
                ),
            ),
        )

    assert not (vault / "proposals").exists()


def test_create_duplicate_scan_ignores_protected_pattern_bytes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
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

    result = propose_agent_pattern(
        vault_root=vault,
        request=ProposeAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            pattern_id="pattern-focus-after-walk",
            title="Focus after walking",
            description="Walking before study may be associated with better focus.",
            semantic=_semantic(),
            evidence=(
                ObservedPatternEvidence(
                    path="journal/source.md",
                    content_hash=source_hash,
                    role="supporting",
                ),
            ),
        ),
    )

    assert result.state == "draft"
    assert result.proposal_id is not None
    assert not (vault / "patterns" / "focus-after-walk.md").exists()


def test_existing_review_treats_reordered_evidence_as_no_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    first_hash = _write_source(vault, "journal/first.md", "Walked, then focused.\n")
    second_hash = _write_source(vault, "journal/second.md", "Focused after another walk.\n")
    first = PatternEvidence(
        path="journal/first.md",
        content_hash=first_hash,
        role="supporting",
    )
    second = PatternEvidence(
        path="journal/second.md",
        content_hash=second_hash,
        role="supporting",
    )
    _write_pattern(
        vault,
        "patterns/focus-after-walk.md",
        pattern_id="pattern-focus-after-walk",
        evidence=(first, second),
    )
    current = PatternArtifactService(vault_root=vault).load("patterns/focus-after-walk.md")

    result = review_agent_pattern(
        vault_root=vault,
        request=ReviewAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            observed_pattern_hash=current.content_hash,
            semantic=_semantic(),
            evidence=(
                ObservedPatternEvidence(
                    path="journal/second.md",
                    content_hash=second_hash,
                    role="supporting",
                ),
                ObservedPatternEvidence(
                    path="journal/first.md",
                    content_hash=first_hash,
                    role="supporting",
                ),
            ),
        ),
    )

    assert result.state == "no-change"
    assert result.proposal_id is None
    assert not (vault / "proposals").exists()
