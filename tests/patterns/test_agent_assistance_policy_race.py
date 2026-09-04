from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.facade.personal_pattern_tools as personal_pattern_tools_module
import lifeos.patterns.agent_assistance as agent_assistance_module
import lifeos.patterns.artifact as pattern_artifact_module
from lifeos.facade.errors import ToolValidationError
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
from lifeos.registry.file_tracking import hash_file_content


def test_policy_revocation_before_persistence_aborts_agent_pattern_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    source = vault / "journal" / "source.md"
    source.parent.mkdir(parents=True)
    content = b"Walked, then completed a focused study block.\n"
    source.write_bytes(content)
    observed_hash = f"sha256:{hash_file_content(content)}"

    original_snapshot = agent_assistance_module.build_review_snapshot_bytes_from_patches

    def revoke_policy(*, vault_root: Path, patches_json: bytes) -> bytes:
        snapshot = original_snapshot(vault_root=vault_root, patches_json=patches_json)
        system = vault_root / "system"
        system.mkdir(exist_ok=True)
        (system / "retrieval-policy.yml").write_text(
            "schema_version: 1\nexcluded_prefixes:\n  - journal\n",
            encoding="utf-8",
        )
        return snapshot

    monkeypatch.setattr(
        agent_assistance_module,
        "build_review_snapshot_bytes_from_patches",
        revoke_policy,
    )

    with pytest.raises(ToolValidationError):
        propose_agent_pattern(
            vault_root=vault,
            request=ProposeAgentPatternRequest(
                target_path="patterns/focus-after-walk.md",
                pattern_id="pattern-focus-after-walk",
                title="Focus after walking",
                description="Walking before study may be associated with better focus.",
                semantic=AgentPatternSemanticInput(
                    hypothesis="Walking before study may improve focus.",
                    rationale="The selected evidence supports review.",
                    proposed_confidence="low",
                ),
                evidence=(
                    ObservedPatternEvidence(
                        path="journal/source.md",
                        content_hash=observed_hash,
                        role="supporting",
                    ),
                ),
            ),
        )

    assert not (vault / "proposals").exists()


def test_policy_revocation_before_identity_scan_prunes_newly_excluded_pattern(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    source = vault / "journal" / "source.md"
    source.parent.mkdir(parents=True)
    content = b"Walked, then completed a focused study block.\n"
    source.write_bytes(content)
    observed_hash = f"sha256:{hash_file_content(content)}"
    evidence = (
        PatternEvidence(
            path="journal/source.md",
            content_hash=observed_hash,
            role="supporting",
        ),
    )

    hidden = vault / "patterns" / "private" / "hidden.md"
    hidden.parent.mkdir(parents=True)
    hidden.write_text(
        serialize_pattern(
            PatternMetadata(
                pattern_id="pattern-focus-after-walk",
                title="Hidden focus pattern",
                description="Protected pattern used to verify current-policy identity pruning.",
                status="seed",
                confidence="low",
                review_reasons=(),
                statement="Hidden pattern content must not influence an external draft.",
                origin=PatternOrigin("human"),
                created_at="2026-09-04T08:00:00Z",
                updated_at="2026-09-04T08:00:00Z",
                evidence_fingerprint=compute_evidence_fingerprint(evidence),
                evidence=evidence,
            )
        ),
        encoding="utf-8",
    )

    system = vault / "system"
    system.mkdir(parents=True)
    policy_path = system / "retrieval-policy.yml"
    policy_path.write_text("schema_version: 1\n", encoding="utf-8")

    original_verified = personal_pattern_tools_module._verified_evidence

    def verify_then_revoke(
        *,
        vault_root: Path,
        evidence: tuple[ObservedPatternEvidence, ...],
        allow_protected: bool,
    ) -> tuple[PatternEvidence, ...]:
        verified = original_verified(
            vault_root=vault_root,
            evidence=evidence,
            allow_protected=allow_protected,
        )
        policy_path.write_text(
            "schema_version: 1\nexcluded_prefixes:\n  - patterns/private\n",
            encoding="utf-8",
        )
        return verified

    monkeypatch.setattr(personal_pattern_tools_module, "_verified_evidence", verify_then_revoke)

    original_read = pattern_artifact_module.read_vault_markdown
    read_paths: list[str] = []

    def recording_read(vault_root: Path, path: str):
        read_paths.append(path)
        return original_read(vault_root, path)

    monkeypatch.setattr(pattern_artifact_module, "read_vault_markdown", recording_read)

    result = propose_agent_pattern(
        vault_root=vault,
        request=ProposeAgentPatternRequest(
            target_path="patterns/focus-after-walk.md",
            pattern_id="pattern-focus-after-walk",
            title="Focus after walking",
            description="Walking before study may be associated with better focus.",
            semantic=AgentPatternSemanticInput(
                hypothesis="Walking before study may improve focus.",
                rationale="The selected evidence supports review.",
                proposed_confidence="low",
            ),
            evidence=(
                ObservedPatternEvidence(
                    path="journal/source.md",
                    content_hash=observed_hash,
                    role="supporting",
                ),
            ),
        ),
    )

    assert result.state == "draft"
    assert result.proposal_id is not None
    assert "patterns/private/hidden.md" not in read_paths
