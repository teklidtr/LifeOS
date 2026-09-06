import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.cli import main
from lifeos.registry._registry import Registry
from lifeos.registry.file_tracking import register_scan
from lifeos.registry.proposals import (
    ProposalScanError,
    list_proposals,
    register_proposals_scan,
)
from lifeos.scanner import scan_vault


@pytest.fixture
def empty_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "init"], cwd=vault, check=True, capture_output=True)
    return vault


def make_proposal(vault_root: Path, pid: str, status: str = "draft", title: str = "Title") -> Path:
    pdir = vault_root / "proposals" / pid
    pdir.mkdir(parents=True, exist_ok=True)

    fm = [
        "---",
        f"id: {pid}",
        "schema_version: 1",
        "patch_schema_version: 1",
        f"title: {title}",
        "description: desc",
        f"status: {status}",
        "risk: low",
        'created_at: "2026-01-01T00:00:00Z"',
        "created_by: author",
        "---",
        "Body",
    ]
    (pdir / "proposal.md").write_text("\n".join(fm))

    patches = {"proposal_id": pid, "schema_version": 1, "operations": []}
    (pdir / "patches.json").write_text(
        json.dumps(patches, sort_keys=True, separators=(",", ":")) + "\n"
    )

    return pdir


def run_cli(capsys: pytest.CaptureFixture[str], args: list[str]) -> tuple[int, str]:
    try:
        code = main(args)
    except SystemExit as exc:
        code = exc.code
    if code is None:
        code = 0
    captured = capsys.readouterr()
    return code, captured.out


def test_proposal_registry_rebuild_is_reproducible(
    empty_vault: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    # config
    config_file = empty_vault / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .lifeos\nfeatures:\n  graphify: true\n  exports: false\n"
    )

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()
    db_path = lifeos_dir / "registry.db"

    # initial setup
    pid_a = "prop-20260101T000000Z-aaaaaaaa"
    pid_b = "prop-20260101T000000Z-bbbbbbbb"
    pid_c = "prop-20260101T000000Z-cccccccc"

    make_proposal(empty_vault, pid_a, title="Proposal A")
    make_proposal(empty_vault, pid_b, title="Proposal B")
    make_proposal(empty_vault, pid_c, title="Proposal C")

    subprocess.run(
        [
            "git",
            "add",
            f"proposals/{pid_a}/proposal.md",
            f"proposals/{pid_a}/patches.json",
            f"proposals/{pid_b}/proposal.md",
            f"proposals/{pid_b}/patches.json",
        ],
        cwd=empty_vault,
        check=True,
    )

    # First build
    registry = Registry(db_path)
    registry.initialize()

    scanned_files = scan_vault(empty_vault)
    register_scan(registry, empty_vault, scanned_files)
    register_proposals_scan(registry, vault_root=empty_vault)

    # Verify first build
    with patch("lifeos.cli.Path", return_value=config_file):
        code, out_list = run_cli(capsys, ["proposals", "list"])
        assert code == 0
        assert pid_a in out_list
        assert pid_b in out_list
        assert pid_c not in out_list

        code, out_status = run_cli(capsys, ["status"])
        assert code == 0
        assert "draft: 2" in out_status

    # Successful reconciliation
    # Transition A to another valid lifecycle status (e.g. approved)
    from lifeos.proposals.loader import load_proposal_directory
    from lifeos.proposals.lifecycle import submit_proposal_for_review, approve_proposal

    proposals_root = empty_vault / "proposals"
    proposal_a_dir = proposals_root / pid_a

    loaded_a_initial = load_proposal_directory(proposal_a_dir, proposals_root=proposals_root)
    assert loaded_a_initial.proposal is not None
    submit_proposal_for_review(
        loaded_a_initial.proposal,
        proposals_root=proposals_root,
        submitted_by="author",
        submitted_at="2026-01-02T00:00:00Z",
    )
    loaded_a_submitted = load_proposal_directory(proposal_a_dir, proposals_root=proposals_root)
    assert loaded_a_submitted.proposal is not None
    approve_proposal(
        loaded_a_submitted.proposal,
        proposals_root=proposals_root,
        approved_by="author",
        approved_at="2026-01-03T00:00:00Z",
    )

    subprocess.run(
        [
            "git",
            "add",
            f"proposals/{pid_a}/proposal.md",
            f"proposals/{pid_a}/patches.json",
        ],
        cwd=empty_vault,
        check=True,
    )

    # Remove B from git using git rm
    subprocess.run(
        [
            "git",
            "rm",
            "--cached",
            f"proposals/{pid_b}/proposal.md",
            f"proposals/{pid_b}/patches.json",
        ],
        cwd=empty_vault,
        check=True,
    )

    # Leave C untracked

    # Run normal proposal scan again
    scanned_files = scan_vault(empty_vault)
    register_scan(registry, empty_vault, scanned_files)
    register_proposals_scan(registry, vault_root=empty_vault)

    # Verify new state
    with patch("lifeos.cli.Path", return_value=config_file):
        code, out_list_mutated = run_cli(capsys, ["proposals", "list"])
        assert code == 0
        assert pid_a in out_list_mutated
        assert pid_b not in out_list_mutated
        assert "approved" in out_list_mutated

        code, out_status_mutated = run_cli(capsys, ["status"])
        assert code == 0
        assert "approved: 1" in out_status_mutated
        assert "draft: 0" in out_status_mutated

    with registry.connect() as conn:
        typed_summaries_mutated = list_proposals(conn)

    # Capture canonical Markdown bytes
    canonical_a_bytes = (empty_vault / "proposals" / pid_a / "proposal.md").read_bytes()
    canonical_b_bytes = (empty_vault / "proposals" / pid_b / "proposal.md").read_bytes()
    canonical_c_bytes = (empty_vault / "proposals" / pid_c / "proposal.md").read_bytes()

    # Destruction and rebuild
    # Close all database connections -> automatically done by context managers
    db_path.unlink()

    # Rebuild
    registry = Registry(db_path)
    registry.initialize()
    scanned_files = scan_vault(empty_vault)
    register_scan(registry, empty_vault, scanned_files)
    register_proposals_scan(registry, vault_root=empty_vault)

    # Verify identical output
    with patch("lifeos.cli.Path", return_value=config_file):
        code, out_list_rebuilt = run_cli(capsys, ["proposals", "list"])
        assert code == 0
        assert out_list_rebuilt == out_list_mutated

        code, out_status_rebuilt = run_cli(capsys, ["status"])
        assert code == 0
        assert out_status_rebuilt == out_status_mutated

    with registry.connect() as conn:
        typed_summaries_rebuilt = list_proposals(conn)

    assert typed_summaries_rebuilt == typed_summaries_mutated

    # Verify canonical Markdown bytes are unchanged
    assert (empty_vault / "proposals" / pid_a / "proposal.md").read_bytes() == canonical_a_bytes
    assert (empty_vault / "proposals" / pid_b / "proposal.md").read_bytes() == canonical_b_bytes
    assert (empty_vault / "proposals" / pid_c / "proposal.md").read_bytes() == canonical_c_bytes


def test_malformed_tracked_proposal_preserves_previous_index(
    empty_vault: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(empty_vault)
    config_file = empty_vault / "lifeos.yml"
    config_file.write_text(
        "vault_root: .\nruntime_dir: .lifeos\nfeatures:\n  graphify: true\n  exports: false\n"
    )

    lifeos_dir = empty_vault / ".lifeos"
    lifeos_dir.mkdir()
    db_path = lifeos_dir / "registry.db"

    pid_a = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(empty_vault, pid_a, title="Proposal A")
    subprocess.run(["git", "add", f"proposals/{pid_a}/proposal.md"], cwd=empty_vault, check=True)

    registry = Registry(db_path)
    registry.initialize()

    scanned_files = scan_vault(empty_vault)
    register_scan(registry, empty_vault, scanned_files)
    register_proposals_scan(registry, vault_root=empty_vault)

    with registry.connect() as conn:
        typed_summaries_initial = list_proposals(conn)

    with patch("lifeos.cli.Path", return_value=config_file):
        code, out_list_initial = run_cli(capsys, ["proposals", "list"])

    # Corrupt the tracked working-tree proposal.md
    proposal_path = empty_vault / "proposals" / pid_a / "proposal.md"
    proposal_path.write_text("---\nbad_yaml: [\n---\nBody")
    corrupt_bytes = proposal_path.read_bytes()

    # run register_proposals_scan() and assert it raises
    with pytest.raises(ProposalScanError):
        register_proposals_scan(registry, vault_root=empty_vault)

    # Assert previous rows remain exactly unchanged
    with registry.connect() as conn:
        typed_summaries_after_error = list_proposals(conn)
    assert typed_summaries_after_error == typed_summaries_initial

    # Assert CLI list still reflects previous index
    with patch("lifeos.cli.Path", return_value=config_file):
        code, out_list_after_error = run_cli(capsys, ["proposals", "list"])
    assert out_list_after_error == out_list_initial

    # Assert malformed Markdown is not rewritten
    assert proposal_path.read_bytes() == corrupt_bytes
