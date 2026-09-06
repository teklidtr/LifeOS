import json
import hashlib
from pathlib import Path

from lifeos.ownership import DEFAULT_OWNERSHIP_MANIFEST_PATH
from lifeos.proposals import (
    LoadedProposal,
    PatchDocumentV2,
    CreateGeneratedFileV2,
    ReplaceGeneratedFileV2,
    ProposalMetadata,
    preflight_proposal,
)

VALID_PROP_ID = "prop-20260713T000000Z-abcdef12"


def _make_dummy_v2_proposal(operations: list) -> LoadedProposal:
    return LoadedProposal(
        proposal_dir=VALID_PROP_ID,
        proposal_path=f"{VALID_PROP_ID}/proposal.md",
        patches_path=f"{VALID_PROP_ID}/patches.json",
        proposal_source_hash="sha256:dummy",
        patches_source_hash="sha256:dummy",
        metadata=ProposalMetadata(
            id=VALID_PROP_ID,
            schema_version=1,
            patch_schema_version=2,
            lifecycle_schema_version=None,
            title="Test Proposal",
            description="A test proposal.",
            status="pending",
            risk="low",
            created_at="2026-07-13T00:00:00+00:00",
            created_by="agent",
            submitted_at=None,
            submitted_by=None,
            review_digest=None,
            approved_at=None,
            approved_by=None,
            rejected_at=None,
            rejected_by=None,
            rejection_reason=None,
            applied_at=None,
            applied_by=None,
            related_goals=[],
            related_sources=[],
            extensions={},
        ),
        patch_document=PatchDocumentV2(2, VALID_PROP_ID, tuple(operations)),
        body="",
    )


def test_v2_preflight_integration(tmp_path: Path) -> None:
    manifest_path = tmp_path / DEFAULT_OWNERSHIP_MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text('{"schema_version": 1, "owned_files": {}}')

    # generated creation with absent target is valid
    op1 = CreateGeneratedFileV2("op-1", "absent.txt", "absent", "gen-1", "v1.0.0", "data")
    prop = _make_dummy_v2_proposal([op1])
    res = preflight_proposal(prop, vault_root=tmp_path)
    assert res.operations[0].state == "valid"

    # generated creation with existing target is stale
    (tmp_path / "existing.txt").write_text("hello")
    op2 = CreateGeneratedFileV2("op-2", "existing.txt", "absent", "gen-1", "v1.0.0", "data")
    prop2 = _make_dummy_v2_proposal([op2])
    res2 = preflight_proposal(prop2, vault_root=tmp_path)
    assert res2.operations[0].state == "stale"

    # generated creation with ownership conflict is invalid
    manifest_json = {
        "schema_version": 1,
        "owned_files": {
            "owned.txt": {
                "generator_id": "gen2",
                "generator_version": "1.0",
                "content_hash": "0" * 64,
                "created_at": "2026-07-13T00:00:00+00:00",
                "updated_at": "2026-07-13T00:00:00+00:00",
            }
        },
    }
    manifest_path.write_text(json.dumps(manifest_json))
    op3 = CreateGeneratedFileV2("op-3", "owned.txt", "absent", "gen-1", "v1.0.0", "data")
    prop3 = _make_dummy_v2_proposal([op3])
    res3 = preflight_proposal(prop3, vault_root=tmp_path)
    assert res3.operations[0].state == "invalid"
    assert res3.operations[0].findings[0].code == "ownership_conflict"

    # replacement checks expected generator ID
    content = b"gencontent"
    raw_digest = hashlib.sha256(content).hexdigest()
    (tmp_path / "owned.txt").write_bytes(content)
    manifest_json["owned_files"]["owned.txt"]["content_hash"] = raw_digest
    manifest_path.write_text(json.dumps(manifest_json))

    op4 = ReplaceGeneratedFileV2(
        "op-4", "owned.txt", "sha256:" + raw_digest, "wrong-gen", "v2.0.0", "newdata"
    )
    prop4 = _make_dummy_v2_proposal([op4])
    res4 = preflight_proposal(prop4, vault_root=tmp_path)
    assert res4.operations[0].state == "invalid"
    assert res4.operations[0].findings[0].code == "generator_mismatch"

    # replacement checks ownership content hash
    # (validation.py enforces hash_mismatch correctly)
    op5 = ReplaceGeneratedFileV2(
        "op-5", "owned.txt", "sha256:" + "f" * 64, "gen2", "v2.0.0", "newdata"
    )
    prop5 = _make_dummy_v2_proposal([op5])
    res5 = preflight_proposal(prop5, vault_root=tmp_path)
    assert res5.operations[0].state == "stale"
    assert res5.operations[0].findings[0].code == "stale_base_hash"

    # valid replacement
    op6 = ReplaceGeneratedFileV2(
        "op-6", "owned.txt", "sha256:" + raw_digest, "gen2", "v2.0.0", "newdata"
    )
    prop6 = _make_dummy_v2_proposal([op6])
    res6 = preflight_proposal(prop6, vault_root=tmp_path)
    assert res6.operations[0].state == "valid"

    # ensure no writes occurred
    assert (tmp_path / "absent.txt").exists() is False
    assert (tmp_path / "owned.txt").read_bytes() == content
