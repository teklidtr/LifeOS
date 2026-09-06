from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

import lifeos.proposals.application as application_module
from lifeos._transaction_files import DirectorySyncResult, StagingFile
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.proposals.application import (
    ApplicationError,
    ApplicationErrorCode,
    OperationState,
    apply_proposal,
)
from lifeos.proposals.lifecycle import (
    approve_proposal,
    serialize_proposal_markdown,
    submit_proposal_for_review,
)
from lifeos.proposals.loader import LoadedProposal, load_proposal_directory
from lifeos.proposals.patches import (
    CreateFile,
    PatchDocumentV2,
    ReplaceManagedBlock,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import ProposalMetadata, ProposalStatus, validate_metadata
from lifeos.proposals.validation import preflight_proposal
from lifeos.registry._registry import Registry
from lifeos.registry.proposals import list_proposals, register_proposals_scan


def _proposal_metadata(proposal_id: str) -> ProposalMetadata:
    return validate_metadata(
        {
            "id": proposal_id,
            "schema_version": 1,
            "patch_schema_version": 2,
            "lifecycle_schema_version": None,
            "title": "End-to-end proposal",
            "description": "Exercise the complete proposal lifecycle.",
            "status": "draft",
            "risk": "low",
            "created_at": "2026-07-15T12:00:00Z",
            "created_by": "e2e-test",
            "submitted_at": None,
            "submitted_by": None,
            "review_digest": None,
            "approved_at": None,
            "approved_by": None,
            "rejected_at": None,
            "rejected_by": None,
            "rejection_reason": None,
            "applied_at": None,
            "applied_by": None,
            "related_goals": [],
            "related_sources": [],
            "extensions": {},
        }
    )


def _create_vault(tmp_path: Path) -> tuple[Path, Path, Registry]:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    subprocess.run(
        ["git", "init", "-q"],
        cwd=vault_root,
        check=True,
        capture_output=True,
    )

    proposals_root = vault_root / "proposals"
    proposals_root.mkdir()
    (vault_root / ".lifeos").mkdir()
    system_dir = vault_root / "system"
    system_dir.mkdir()
    (system_dir / "generated-ownership.json").write_bytes(serialize_generated_ownership_bytes({}))

    registry = Registry(vault_root / ".lifeos" / "registry.db")
    registry.initialize()
    return vault_root, proposals_root, registry


def _write_proposal(
    *,
    vault_root: Path,
    proposals_root: Path,
    metadata: ProposalMetadata,
    patch_document: PatchDocumentV2,
) -> Path:
    proposal_dir = proposals_root / metadata.id
    proposal_dir.mkdir()
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(metadata, "End-to-end test proposal body.")
    )
    (proposal_dir / "patches.json").write_bytes(serialize_patch_json_bytes(patch_document))
    subprocess.run(
        [
            "git",
            "add",
            f"proposals/{metadata.id}/proposal.md",
            f"proposals/{metadata.id}/patches.json",
        ],
        cwd=vault_root,
        check=True,
        capture_output=True,
    )
    return proposal_dir


def _load(proposal_dir: Path, proposals_root: Path) -> LoadedProposal:
    result = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


def _indexed_status(registry: Registry, *, vault_root: Path, proposal_id: str) -> ProposalStatus:
    register_proposals_scan(registry, vault_root=vault_root)
    with registry.connect() as connection:
        summaries = list_proposals(connection)
    assert len(summaries) == 1
    assert summaries[0].id == proposal_id
    return summaries[0].status


def _submit_and_approve(proposal_dir: Path, proposals_root: Path) -> LoadedProposal:
    draft = _load(proposal_dir, proposals_root)
    submit_proposal_for_review(
        draft,
        proposals_root=proposals_root,
        submitted_by="reviewer",
        submitted_at="2026-07-15T12:01:00Z",
    )
    pending = _load(proposal_dir, proposals_root)
    assert pending.metadata.status is ProposalStatus.PENDING

    approve_proposal(
        pending,
        proposals_root=proposals_root,
        approved_by="approver",
        approved_at="2026-07-15T12:02:00Z",
    )
    approved = _load(proposal_dir, proposals_root)
    assert approved.metadata.status is ProposalStatus.APPROVED
    return approved


def test_managed_block_happy_path_through_index_and_application(
    tmp_path: Path,
) -> None:
    vault_root, proposals_root, registry = _create_vault(tmp_path)
    target_path = vault_root / "wiki.md"
    original = (
        "# Topic\n\n"
        "<!-- lifeos:managed:start summary -->\n"
        "Old summary.\n"
        "<!-- lifeos:managed:end summary -->\n"
    )
    target_path.write_text(original)

    metadata = _proposal_metadata("prop-20260715T120000Z-a1b2c3d4")
    operation = ReplaceManagedBlock(
        "op-summary",
        "wiki.md",
        f"sha256:{hashlib.sha256(original.encode()).hexdigest()}",
        "summary",
        "New summary.\n",
    )
    proposal_dir = _write_proposal(
        vault_root=vault_root,
        proposals_root=proposals_root,
        metadata=metadata,
        patch_document=PatchDocumentV2(2, metadata.id, (operation,)),
    )

    draft = _load(proposal_dir, proposals_root)
    assert draft.metadata.status is ProposalStatus.DRAFT
    assert preflight_proposal(draft, vault_root=vault_root).state == "valid"

    submit_proposal_for_review(
        draft,
        proposals_root=proposals_root,
        submitted_by="reviewer",
        submitted_at="2026-07-15T12:01:00Z",
    )
    assert (
        _indexed_status(registry, vault_root=vault_root, proposal_id=metadata.id)
        is ProposalStatus.PENDING
    )

    pending = _load(proposal_dir, proposals_root)
    approve_proposal(
        pending,
        proposals_root=proposals_root,
        approved_by="approver",
        approved_at="2026-07-15T12:02:00Z",
    )
    assert (
        _indexed_status(registry, vault_root=vault_root, proposal_id=metadata.id)
        is ProposalStatus.APPROVED
    )

    approved = _load(proposal_dir, proposals_root)
    result = apply_proposal(
        approved,
        vault_root=vault_root,
        applied_by="operator",
        applied_at="2026-07-15T12:03:00Z",
    )

    assert result.new_status is ProposalStatus.APPLIED
    assert result.changed_paths == ("wiki.md",)
    assert target_path.read_text() == (
        "# Topic\n\n"
        "<!-- lifeos:managed:start summary -->\n"
        "New summary.\n"
        "<!-- lifeos:managed:end summary -->\n"
    )
    assert _load(proposal_dir, proposals_root).metadata.status is ProposalStatus.APPLIED
    assert (
        _indexed_status(registry, vault_root=vault_root, proposal_id=metadata.id)
        is ProposalStatus.APPLIED
    )


def test_stale_target_blocks_approved_proposal_without_touching_target(
    tmp_path: Path,
) -> None:
    vault_root, proposals_root, registry = _create_vault(tmp_path)
    target_path = vault_root / "wiki.md"
    original = (
        "<!-- lifeos:managed:start summary -->\nOriginal.\n<!-- lifeos:managed:end summary -->\n"
    )
    target_path.write_text(original)

    metadata = _proposal_metadata("prop-20260715T120100Z-b1c2d3e4")
    operation = ReplaceManagedBlock(
        "op-summary",
        "wiki.md",
        f"sha256:{hashlib.sha256(original.encode()).hexdigest()}",
        "summary",
        "Proposed.\n",
    )
    proposal_dir = _write_proposal(
        vault_root=vault_root,
        proposals_root=proposals_root,
        metadata=metadata,
        patch_document=PatchDocumentV2(2, metadata.id, (operation,)),
    )
    approved = _submit_and_approve(proposal_dir, proposals_root)

    externally_modified = original.replace("Original.", "External edit.")
    target_path.write_text(externally_modified)
    before_apply = target_path.read_bytes()

    preflight = preflight_proposal(approved, vault_root=vault_root)
    assert preflight.state == "stale"
    assert preflight.operations[0].state == "stale"

    with pytest.raises(ApplicationError) as captured:
        apply_proposal(
            approved,
            vault_root=vault_root,
            applied_by="operator",
            applied_at="2026-07-15T12:03:00Z",
        )

    assert captured.value.code is ApplicationErrorCode.PREFLIGHT_FAILED
    assert target_path.read_bytes() == before_apply
    assert _load(proposal_dir, proposals_root).metadata.status is ProposalStatus.APPROVED
    assert (
        _indexed_status(registry, vault_root=vault_root, proposal_id=metadata.id)
        is ProposalStatus.APPROVED
    )


def test_second_creation_failure_rolls_back_first_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root, proposals_root, registry = _create_vault(tmp_path)
    metadata = _proposal_metadata("prop-20260715T120200Z-c1d2e3f4")
    operations = (
        CreateFile("op-first", "first.txt", "absent", "first content"),
        CreateFile("op-second", "second.txt", "absent", "second content"),
    )
    proposal_dir = _write_proposal(
        vault_root=vault_root,
        proposals_root=proposals_root,
        metadata=metadata,
        patch_document=PatchDocumentV2(2, metadata.id, operations),
    )
    approved = _submit_and_approve(proposal_dir, proposals_root)

    original_publish_creation = application_module.publish_creation

    def fail_second_creation(target_name: str, staging: StagingFile) -> DirectorySyncResult:
        if target_name == "second.txt":
            raise OSError("simulated second-target publication failure")
        return original_publish_creation(target_name, staging)

    monkeypatch.setattr(application_module, "publish_creation", fail_second_creation)

    with pytest.raises(ApplicationError) as captured:
        apply_proposal(
            approved,
            vault_root=vault_root,
            applied_by="operator",
            applied_at="2026-07-15T12:03:00Z",
        )

    error = captured.value
    assert error.code is ApplicationErrorCode.COMMIT_FAILED
    assert error.outcome.rollback_performed is True
    assert error.outcome.rollback_succeeded is True
    assert error.outcome.recovery_required is False
    assert error.outcome.operation_results[0].state is OperationState.ROLLED_BACK
    assert error.outcome.operation_results[1].state is OperationState.PREPARED
    assert not (vault_root / "first.txt").exists()
    assert not (vault_root / "second.txt").exists()
    assert _load(proposal_dir, proposals_root).metadata.status is ProposalStatus.APPROVED
    assert (
        _indexed_status(registry, vault_root=vault_root, proposal_id=metadata.id)
        is ProposalStatus.APPROVED
    )
