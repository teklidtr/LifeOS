import json
from datetime import datetime, timezone
from pathlib import Path

from lifeos.desktop import DesktopProposalService
from lifeos.ownership import (
    create_ownership_release_proposal,
    list_orphaned_generated_ownership,
)
from lifeos.proposals import preflight_proposal
from lifeos.proposals.loader import load_proposal_directory


TARGET = "wiki/missing-generated.md"
ENTRY = {
    "generator_id": "lifeos.test",
    "generator_version": "1",
    "content_hash": "a" * 64,
    "created_at": "2026-08-22T10:00:00Z",
    "updated_at": "2026-08-22T11:00:00Z",
}


def _write_manifest(vault_root: Path) -> Path:
    manifest = vault_root / "system/generated-ownership.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {"schema_version": 1, "owned_files": {TARGET: ENTRY}},
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def test_orphan_diagnostics_are_deterministic_and_read_only(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    before = manifest.read_bytes()

    first = list_orphaned_generated_ownership(tmp_path)
    second = list_orphaned_generated_ownership(tmp_path)

    assert first == second
    assert len(first) == 1
    orphan = first[0]
    assert orphan.target_path == TARGET
    assert orphan.content_hash == ENTRY["content_hash"]
    assert orphan.generator_id == ENTRY["generator_id"]
    assert orphan.generator_version == ENTRY["generator_version"]
    assert orphan.created_at == ENTRY["created_at"]
    assert orphan.updated_at == ENTRY["updated_at"]
    assert orphan.diagnostic_code == "owned_target_missing"
    assert "SHA-256" in orphan.restore_instructions
    assert manifest.read_bytes() == before


def test_restore_hides_orphan_without_mutating_ownership(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    before = manifest.read_bytes()
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("restored", encoding="utf-8")

    assert list_orphaned_generated_ownership(tmp_path) == ()
    assert manifest.read_bytes() == before


def test_release_is_reviewed_and_applied_as_a_proposal(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    result = create_ownership_release_proposal(
        vault_root=tmp_path,
        target_path=TARGET,
        created_by="tester",
        now=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )
    proposal_dir = tmp_path / result.proposal_path
    loaded = load_proposal_directory(
        proposal_dir,
        proposals_root=tmp_path / "proposals",
    )
    assert loaded.proposal is not None, loaded.findings
    assert loaded.proposal.metadata.status.value == "draft"
    assert loaded.proposal.patch_document.operations[0].op == "release_generated_ownership"
    assert preflight_proposal(loaded.proposal, vault_root=tmp_path).state == "valid"

    service = DesktopProposalService(vault_root=tmp_path, actor_id="tester")
    inspection = service.inspect(result.proposal_id)
    assert f'-    "{TARGET}": {{' in inspection.operations[0].unified_diff
    challenge = service.prepare(proposal_id=result.proposal_id, action="accept")
    applied = service.execute(
        proposal_id=result.proposal_id,
        action="accept",
        token=challenge.token,
    )

    assert applied["status"] == "applied"
    assert applied["changed_paths"] == ("system/generated-ownership.json",)
    assert json.loads(manifest.read_text(encoding="utf-8"))["owned_files"] == {}
    assert list_orphaned_generated_ownership(tmp_path) == ()


def test_release_proposal_becomes_stale_when_target_is_restored(tmp_path: Path) -> None:
    _write_manifest(tmp_path)
    result = create_ownership_release_proposal(
        vault_root=tmp_path,
        target_path=TARGET,
        created_by="tester",
        now=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )
    target = tmp_path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("restored", encoding="utf-8")
    loaded = load_proposal_directory(
        tmp_path / result.proposal_path,
        proposals_root=tmp_path / "proposals",
    )

    assert loaded.proposal is not None
    preflight = preflight_proposal(loaded.proposal, vault_root=tmp_path)
    assert preflight.state == "stale"
    assert preflight.operations[0].findings[0].code == "target_restored"
