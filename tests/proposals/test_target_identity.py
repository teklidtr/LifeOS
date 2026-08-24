from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lifeos.coherence import collect_identity_snapshot
from lifeos.proposals.patches import CreateGeneratedFileV2, PatchDocumentV2, PatchHumanFile
from lifeos.proposals.schema import ProposalMetadata, ProposalRisk, ProposalStatus
from lifeos.proposals.target_identity import (
    ProposalTargetIdentityError,
    assess_proposal_target_identities,
    parse_target_identities,
    with_target_identity_extension,
)

PROPOSAL_ID = "prop-20260824T120000Z-1234abcd"


def _note(stable_id: str, body: str = "# Section\nReviewed\n") -> str:
    return f"---\nid: {stable_id}\ntype: wiki\ntitle: Example\n---\n{body}"


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _metadata(status: ProposalStatus = ProposalStatus.DRAFT) -> ProposalMetadata:
    submitted = status is not ProposalStatus.DRAFT
    approved = status in {ProposalStatus.APPROVED, ProposalStatus.APPLIED}
    applied = status is ProposalStatus.APPLIED
    return ProposalMetadata(
        id=PROPOSAL_ID,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title="Test proposal",
        description="Test",
        status=status,
        risk=ProposalRisk.MEDIUM,
        created_at="2026-08-24T12:00:00Z",
        created_by="agent",
        submitted_at="2026-08-24T12:01:00Z" if submitted else None,
        submitted_by="human" if submitted else None,
        review_digest="sha256:" + "1" * 64 if submitted else None,
        approved_at="2026-08-24T12:02:00Z" if approved else None,
        approved_by="human" if approved else None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at="2026-08-24T12:03:00Z" if applied else None,
        applied_by="human" if applied else None,
        related_goals=(),
        related_sources=(),
        extensions={"existing": {"kept": True}},
    )


def test_replacement_operation_retains_review_bound_stable_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    (vault / "wiki" / "target.md").write_text(content, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/target.md",
                base_hash=_hash(content),
                unified_diff="@@ -1 +1 @@\n-old\n+new\n",
            ),
        ),
    )

    metadata = with_target_identity_extension(_metadata(), patch, snapshot)
    targets = parse_target_identities(metadata, patch)

    assert metadata.extensions["existing"] == {"kept": True}
    assert len(targets) == 1
    assert targets[0].operation_id == "op-update"
    assert targets[0].stable_id == "wiki-example"
    assert targets[0].reviewed_path == "wiki/target.md"
    assert targets[0].reviewed_base_hash == _hash(content)


def test_create_operations_remain_path_oriented(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    snapshot = collect_identity_snapshot(vault)
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            CreateGeneratedFileV2(
                id="op-create",
                target_path="wiki/new.md",
                expected_target_state="absent",
                generator_id="lifeos.test",
                generator_version="1",
                new_content=_note("wiki-new"),
            ),
        ),
    )

    metadata = with_target_identity_extension(_metadata(), patch, snapshot)

    assert "lifeos_target_identity" not in metadata.extensions
    assert parse_target_identities(metadata, patch) == ()


def test_identity_extension_rejects_patch_mismatch(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    (vault / "wiki" / "target.md").write_text(content, encoding="utf-8")
    snapshot = collect_identity_snapshot(vault)
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/target.md",
                base_hash=_hash(content),
                unified_diff="@@ -1 +1 @@\n-old\n+new\n",
            ),
        ),
    )
    metadata = with_target_identity_extension(_metadata(), patch, snapshot)
    changed_patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/other.md",
                base_hash=_hash(content),
                unified_diff="@@ -1 +1 @@\n-old\n+new\n",
            ),
        ),
    )

    with pytest.raises(ProposalTargetIdentityError, match="does not match"):
        parse_target_identities(metadata, changed_patch)


def test_approved_bound_target_move_requires_review_again(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    original = vault / "wiki" / "target.md"
    original.write_text(content, encoding="utf-8")
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/target.md",
                base_hash=_hash(content),
                unified_diff="@@ -1 +1 @@\n-old\n+new\n",
            ),
        ),
    )
    metadata = with_target_identity_extension(
        _metadata(ProposalStatus.APPROVED),
        patch,
        collect_identity_snapshot(vault),
    )
    original.rename(vault / "wiki" / "moved.md")

    resolutions = assess_proposal_target_identities(
        metadata,
        patch,
        collect_identity_snapshot(vault),
    )

    assert resolutions["op-update"].state == "relocated-review-required"
    assert resolutions["op-update"].current_path == "wiki/moved.md"
    assert resolutions["op-update"].may_apply_without_new_review is False


def test_binding_rejects_stale_base_hash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    content = _note("wiki-example")
    (vault / "wiki" / "target.md").write_text(content, encoding="utf-8")
    patch = PatchDocumentV2(
        schema_version=2,
        proposal_id=PROPOSAL_ID,
        operations=(
            PatchHumanFile(
                id="op-update",
                target_path="wiki/target.md",
                base_hash="sha256:" + "0" * 64,
                unified_diff="@@ -1 +1 @@\n-old\n+new\n",
            ),
        ),
    )

    with pytest.raises(ProposalTargetIdentityError, match="base hash"):
        with_target_identity_extension(_metadata(), patch, collect_identity_snapshot(vault))
