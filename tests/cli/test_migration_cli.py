from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.cli import main
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.patches import PatchDocument, serialize_patch_json_bytes
from lifeos.proposals.schema import ProposalMetadata, validate_metadata


def _legacy_pending(proposal_id: str) -> ProposalMetadata:
    return validate_metadata(
        {
            "id": proposal_id,
            "schema_version": 1,
            "patch_schema_version": 1,
            "lifecycle_schema_version": None,
            "title": "Legacy pending proposal",
            "description": "Needs lifecycle migration.",
            "status": "pending",
            "risk": "low",
            "created_at": "2026-07-01T10:00:00Z",
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


def _configure_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "proposals").mkdir()
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault_root}\nruntime_dir: .lifeos\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return vault_root


def _write_proposal(vault_root: Path, metadata: ProposalMetadata) -> Path:
    proposals_root = vault_root / "proposals"
    proposal_dir = proposals_root / metadata.id
    proposal_dir.mkdir()
    (proposal_dir / "proposal.md").write_bytes(
        serialize_proposal_markdown(metadata, "CLI migration body.\n")
    )
    (proposal_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(PatchDocument(1, metadata.id, ()))
    )
    return proposal_dir


def test_migrate_lifecycle_dry_run_reports_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault_root = _configure_vault(tmp_path, monkeypatch)
    metadata = _legacy_pending("prop-20260701T100000Z-a1b2c3d4")
    proposal_dir = _write_proposal(vault_root, metadata)
    original = (proposal_dir / "proposal.md").read_bytes()

    exit_code = main(["proposals", "migrate-lifecycle", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "1 candidate(s), 0 current, 0 warning(s)" in captured.out
    assert f"Would migrate {metadata.id} (pending)." in captured.out
    assert (proposal_dir / "proposal.md").read_bytes() == original


def test_migrate_lifecycle_writes_and_reports_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault_root = _configure_vault(tmp_path, monkeypatch)
    metadata = _legacy_pending("prop-20260701T100000Z-a1b2c3d4")
    proposal_dir = _write_proposal(vault_root, metadata)

    exit_code = main(["proposals", "migrate-lifecycle"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "1 migrated, 0 current, 0 warning(s)" in captured.out
    assert f"Migrated {metadata.id} (pending)." in captured.out

    loaded = load_proposal_directory(
        proposal_dir,
        proposals_root=vault_root / "proposals",
    )
    assert loaded.findings == ()
    assert loaded.proposal is not None
    assert loaded.proposal.metadata.lifecycle_schema_version == 1

    second_exit = main(["proposals", "migrate-lifecycle"])
    second = capsys.readouterr()
    assert second_exit == 0
    assert "0 migrated, 1 current, 0 warning(s)" in second.out


def test_migrate_lifecycle_scan_error_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault_root = _configure_vault(tmp_path, monkeypatch)
    proposal_dir = vault_root / "proposals" / "prop-20260701T100000Z-a1b2c3d4"
    proposal_dir.mkdir()
    (proposal_dir / "proposal.md").write_text("malformed", encoding="utf-8")
    (proposal_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(PatchDocument(1, proposal_dir.name, ()))
    )

    exit_code = main(["proposals", "migrate-lifecycle"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Migration error: scan_failed" in captured.err
