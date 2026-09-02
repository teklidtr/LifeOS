import hashlib
import json
import os
from unittest import mock

import pytest

import lifeos.proposals.application as application_module
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import serialize_proposal_markdown, submit_proposal_for_review
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import (
    CreateGeneratedFileV2,
    PatchDocument,
    PatchDocumentV2,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import ProposalStatus, validate_metadata


def _draft_metadata():
    return validate_metadata(
        {
            "id": "prop-20260902T170000Z-a1b2c3d4",
            "schema_version": 1,
            "patch_schema_version": 1,
            "lifecycle_schema_version": None,
            "title": "Draft",
            "description": "Lock boundary regression",
            "status": "draft",
            "risk": "low",
            "created_at": "2026-09-02T17:00:00Z",
            "created_by": "system",
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


def _approved_metadata():
    return validate_metadata(
        {
            "id": "prop-20260902T171000Z-b1c2d3e4",
            "schema_version": 1,
            "patch_schema_version": 2,
            "lifecycle_schema_version": 1,
            "title": "Approved",
            "description": "Lock boundary regression",
            "status": "approved",
            "risk": "low",
            "created_at": "2026-09-02T17:10:00Z",
            "created_by": "system",
            "submitted_at": "2026-09-02T17:11:00Z",
            "submitted_by": "user",
            "review_digest": f"sha256:{hashlib.sha256(b'approved').hexdigest()}",
            "approved_at": "2026-09-02T17:12:00Z",
            "approved_by": "user",
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


def _write_proposal(proposals_root, metadata, patch_document):
    proposal_dir = proposals_root / metadata.id
    proposal_dir.mkdir()
    (proposal_dir / "proposal.md").write_bytes(serialize_proposal_markdown(metadata, "body"))
    (proposal_dir / "patches.json").write_bytes(serialize_patch_json_bytes(patch_document))
    return proposal_dir


def test_lifecycle_lock_initialization_failure_preserves_proposal_and_allows_retry(
    tmp_path, monkeypatch
):
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _draft_metadata()
    patch_document = PatchDocument(1, metadata.id, ())
    proposal_dir = _write_proposal(proposals_root, metadata, patch_document)
    proposal_path = proposal_dir / "proposal.md"
    original_proposal = proposal_path.read_bytes()
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root).proposal
    assert loaded is not None

    original_fsync = os.fsync
    failed = False

    def fail_once(sync_fd):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("lock sync failed")
        return original_fsync(sync_fd)

    with mock.patch("lifeos._owned_lock.os.fsync", side_effect=fail_once):
        with pytest.raises(OSError, match="lock sync failed"):
            submit_proposal_for_review(
                loaded,
                proposals_root=proposals_root,
                submitted_by="user",
                submitted_at="2026-09-02T17:20:00Z",
            )

    assert proposal_path.read_bytes() == original_proposal
    assert not (proposal_dir / ".lifeos-transition.lock").exists()

    retry = load_proposal_directory(proposal_dir, proposals_root=proposals_root).proposal
    assert retry is not None
    result = submit_proposal_for_review(
        retry,
        proposals_root=proposals_root,
        submitted_by="user",
        submitted_at="2026-09-02T17:20:00Z",
    )

    assert result.new_status is ProposalStatus.PENDING
    assert result.write_occurred is True
    assert result.lock_released is True
    assert not (proposal_dir / ".lifeos-transition.lock").exists()


def test_application_lock_initialization_failure_preserves_canonical_state_and_allows_retry(
    tmp_path, monkeypatch
):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    proposals_root = vault_root / "proposals"
    proposals_root.mkdir()
    system_dir = vault_root / "system"
    system_dir.mkdir()
    manifest_path = system_dir / "generated-ownership.json"
    manifest_bytes = json.dumps({"schema_version": 1, "owned_files": {}}).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)

    metadata = _approved_metadata()
    operation = CreateGeneratedFileV2(
        "op-1",
        "output.txt",
        "absent",
        "test-generator",
        "v1",
        "generated",
    )
    patch_document = PatchDocumentV2(2, metadata.id, (operation,))
    proposal_dir = _write_proposal(proposals_root, metadata, patch_document)
    proposal_path = proposal_dir / "proposal.md"
    original_proposal = proposal_path.read_bytes()
    loaded = load_proposal_directory(proposal_dir, proposals_root=proposals_root).proposal
    assert loaded is not None

    owned_lock_type = application_module.OwnedLock

    class FailFirstOwnedLock(owned_lock_type):
        fail_next = True

        def acquire(self):
            if type(self).fail_next:
                type(self).fail_next = False
                with mock.patch(
                    "lifeos._owned_lock.os.fsync",
                    side_effect=OSError("lock sync failed"),
                ):
                    return super().acquire()
            return super().acquire()

    monkeypatch.setattr(application_module, "OwnedLock", FailFirstOwnedLock)

    with pytest.raises(OSError, match="lock sync failed"):
        apply_proposal(
            loaded,
            vault_root=vault_root,
            applied_by="user",
            applied_at="2026-09-02T17:30:00Z",
        )

    assert proposal_path.read_bytes() == original_proposal
    assert manifest_path.read_bytes() == manifest_bytes
    assert not (vault_root / "output.txt").exists()
    assert not (vault_root / ".lifeos" / "locks" / "vault-mutation.lock").exists()

    retry = load_proposal_directory(proposal_dir, proposals_root=proposals_root).proposal
    assert retry is not None
    result = apply_proposal(
        retry,
        vault_root=vault_root,
        applied_by="user",
        applied_at="2026-09-02T17:30:00Z",
    )

    assert result.new_status is ProposalStatus.APPLIED
    assert (vault_root / "output.txt").read_text() == "generated"
    assert result.vault_lock_released is True
    assert result.proposal_lock_released is True
