from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import lifeos.coherence_scoped as coherence_scoped
import lifeos.proposals.coherence_validation as coherence_validation
from lifeos.coherence import collect_identity_snapshot
from lifeos.proposals.loader import LoadedProposal
from lifeos.proposals.patches import PatchDocumentV2, PatchHumanFile
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus
from lifeos.proposals.target_identity import with_target_identity_extension
from lifeos.proposals.validation import OperationPreflightResult, ProposalPreflightResult

PROPOSAL_ID = "prop-20260824T183500Z-abcdef12"


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
        title="Privacy-scoped target review",
        description="Test",
        status=ProposalStatus.APPROVED,
        risk=ProposalRisk.MEDIUM,
        created_at="2026-08-24T18:30:00Z",
        created_by="agent",
        submitted_at="2026-08-24T18:31:00Z",
        submitted_by="human",
        review_digest="sha256:" + "1" * 64,
        approved_at="2026-08-24T18:32:00Z",
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


def test_public_proposal_identity_preflight_never_reads_protected_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    metadata = with_target_identity_extension(_metadata(), patch, collect_identity_snapshot(vault))
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

    protected = vault / "private" / "duplicate.md"
    protected.parent.mkdir(parents=True)
    protected.write_text(content, encoding="utf-8")
    real_read = coherence_scoped.read_vault_markdown
    read_paths: list[str] = []

    def recording_read(root: Path, relative_path: str):
        read_paths.append(relative_path)
        if relative_path.startswith("private/"):
            raise AssertionError("protected note content must not be read")
        return real_read(root, relative_path)

    monkeypatch.setattr(coherence_scoped, "read_vault_markdown", recording_read)

    result = coherence_validation.preflight_proposal(loaded, vault_root=vault)

    assert result.state == "valid"
    assert read_paths == ["wiki/target.md"]
