from __future__ import annotations

import hashlib
from pathlib import Path

import lifeos.proposals.coherence_validation as coherence_validation
from lifeos.coherence import collect_identity_snapshot
from lifeos.proposals import preflight_proposal
from lifeos.proposals.loader import LoadedProposal
from lifeos.proposals.patches import PatchDocumentV2, PatchHumanFile
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus
from lifeos.proposals.target_identity import with_target_identity_extension
from lifeos.proposals.validation import OperationPreflightResult, ProposalPreflightResult

PROPOSAL_ID = "prop-20260824T120000Z-1234abcd"


def _content() -> str:
    return "---\nid: stable-target\ntype: concept\ntitle: Target\n---\n# Section\nReviewed\n"


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _metadata() -> ProposalMetadata:
    return ProposalMetadata(
        id=PROPOSAL_ID,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title="Move-safe review",
        description="Test",
        status=ProposalStatus.APPROVED,
        risk=ProposalRisk.MEDIUM,
        created_at="2026-08-24T12:00:00Z",
        created_by="agent",
        submitted_at="2026-08-24T12:01:00Z",
        submitted_by="human",
        review_digest="sha256:" + "1" * 64,
        approved_at="2026-08-24T12:02:00Z",
        approved_by="human",
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at=None,
        applied_by=None,
        related_goals=(),
        related_sources=(),
        extensions={},
    )


def test_public_preflight_blocks_approved_target_after_pure_relocation(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    original = vault / "wiki" / "before.md"
    original.parent.mkdir(parents=True)
    content = _content()
    original.write_text(content, encoding="utf-8")
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/before.md",
                base_hash=_hash(content),
                unified_diff="@@ -6 +6 @@\n-Reviewed\n+Changed\n",
            ),
        ),
    )
    metadata = with_target_identity_extension(
        _metadata(), patch, collect_identity_snapshot(vault)
    )
    loaded = LoadedProposal(
        proposal_dir=PROPOSAL_ID,
        proposal_path=f"{PROPOSAL_ID}/proposal.md",
        patches_path=f"{PROPOSAL_ID}/patches.json",
        proposal_source_hash="sha256:" + "2" * 64,
        patches_source_hash="sha256:" + "3" * 64,
        metadata=metadata,
        patch_document=patch,
        body="body",
    )
    base = ProposalPreflightResult(
        proposal_id=PROPOSAL_ID,
        state="valid",
        operations=(
            OperationPreflightResult(
                operation_id="op-update",
                target_path="wiki/before.md",
                state="valid",
                findings=(),
            ),
        ),
        findings=(),
    )
    monkeypatch.setattr(
        coherence_validation,
        "_base_preflight_proposal",
        lambda *args, **kwargs: base,
    )
    original.rename(vault / "wiki" / "after.md")

    result = preflight_proposal(loaded, vault_root=vault)

    assert result.state == "stale"
    assert result.operations[0].state == "stale"
    assert result.operations[0].findings[-1].code == "target_identity_relocated_review_required"
    assert "wiki/after.md" in result.operations[0].findings[-1].message


def test_public_preflight_blocks_changed_content_even_with_same_stable_id(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    target = vault / "wiki" / "target.md"
    target.parent.mkdir(parents=True)
    content = _content()
    target.write_text(content, encoding="utf-8")
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/target.md",
                base_hash=_hash(content),
                unified_diff="@@ -6 +6 @@\n-Reviewed\n+Changed\n",
            ),
        ),
    )
    metadata = with_target_identity_extension(
        _metadata(), patch, collect_identity_snapshot(vault)
    )
    loaded = LoadedProposal(
        proposal_dir=PROPOSAL_ID,
        proposal_path=f"{PROPOSAL_ID}/proposal.md",
        patches_path=f"{PROPOSAL_ID}/patches.json",
        proposal_source_hash="sha256:" + "2" * 64,
        patches_source_hash="sha256:" + "3" * 64,
        metadata=metadata,
        patch_document=patch,
        body="body",
    )
    base = ProposalPreflightResult(
        proposal_id=PROPOSAL_ID,
        state="valid",
        operations=(
            OperationPreflightResult(
                operation_id="op-update",
                target_path="wiki/target.md",
                state="valid",
                findings=(),
            ),
        ),
        findings=(),
    )
    monkeypatch.setattr(
        coherence_validation,
        "_base_preflight_proposal",
        lambda *args, **kwargs: base,
    )
    target.write_text(content + "human edit\n", encoding="utf-8")

    result = preflight_proposal(loaded, vault_root=vault)

    assert result.state == "stale"
    assert result.operations[0].findings[-1].code == "target_identity_stale_content"
