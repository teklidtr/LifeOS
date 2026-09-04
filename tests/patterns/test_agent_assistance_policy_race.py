from __future__ import annotations

from pathlib import Path

import pytest

import lifeos.patterns.agent_assistance as agent_assistance_module
from lifeos.facade.errors import ToolValidationError
from lifeos.facade.personal_pattern_tools import (
    AgentPatternSemanticInput,
    ObservedPatternEvidence,
    ProposeAgentPatternRequest,
    propose_agent_pattern,
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
