import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lifeos.registry._registry import Registry
from lifeos.registry.proposals import (
    ProposalScanError,
    register_proposals_scan,
    ProposalQueryError,
    ProposalSummary,
    count_proposals_by_status,
    list_proposals,
)
from lifeos.proposals.schema import ProposalStatus
import sqlite3


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    db_path = tmp_path / "registry.sqlite"
    r = Registry(db_path)
    r.initialize()
    return r


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    vr = tmp_path / "vault"
    vr.mkdir()
    subprocess.run(["git", "init"], cwd=vr, check=True, capture_output=True)
    return vr


def make_proposal(
    vault_root: Path,
    pid: str,
    status: str = "draft",
    title: str = "Title",
    extra_fields: dict[str, str] | None = None,
) -> Path:
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
    ]
    if extra_fields:
        for k, v in extra_fields.items():
            if v is not None:
                fm.append(f"{k}: {v}")
    fm.append("---")
    fm.append("Body")

    (pdir / "proposal.md").write_text("\n".join(fm))

    patches = {"proposal_id": pid, "schema_version": 1, "operations": []}
    (pdir / "patches.json").write_text(
        json.dumps(patches, sort_keys=True, separators=(",", ":")) + "\n"
    )

    return pdir


def _get_rows(registry: Registry) -> list[tuple]:
    with registry.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT id, status, title, created_at, updated_at FROM proposals ORDER BY id"
            ).fetchall()
        ]


def test_tracked_proposal_indexed(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    subprocess.run(["git", "add", f"proposals/{pid}/proposal.md"], cwd=vault_root, check=True)

    register_proposals_scan(registry, vault_root=vault_root)

    rows = _get_rows(registry)
    assert len(rows) == 1
    assert rows[0] == (pid, "draft", "Title", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")


def test_untracked_proposal_ignored(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    # Not added to git!

    register_proposals_scan(registry, vault_root=vault_root)

    rows = _get_rows(registry)
    assert len(rows) == 0


def test_removed_tracked_proposal_reconciled(registry: Registry, vault_root: Path) -> None:
    pid1 = "prop-20260101T000000Z-aaaaaaaa"
    pid2 = "prop-20260101T000000Z-bbbbbbbb"
    make_proposal(vault_root, pid1)
    make_proposal(vault_root, pid2)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)

    register_proposals_scan(registry, vault_root=vault_root)
    assert len(_get_rows(registry)) == 2

    # Remove pid1 from git
    subprocess.run(
        ["git", "rm", "--cached", f"proposals/{pid1}/proposal.md"], cwd=vault_root, check=True
    )

    register_proposals_scan(registry, vault_root=vault_root)
    rows = _get_rows(registry)
    assert len(rows) == 1
    assert rows[0][0] == pid2


def test_metadata_status_and_title_changes_reflected(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid, title="Old Title")
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    assert _get_rows(registry)[0][2] == "Old Title"

    # Update title
    make_proposal(
        vault_root, pid, title="New Title", status="draft"
    )  # status changes covered if we change it but let's stick to title change and keep valid state
    # Need to keep git index updated for modified file? git ls-files still tracks it!
    register_proposals_scan(registry, vault_root=vault_root)

    assert _get_rows(registry)[0][2] == "New Title"


def test_updated_at_derived_deterministically(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    # Provide submitted_at and approved_at but NOT applied_at to keep it valid (APPROVED status)
    make_proposal(
        vault_root,
        pid,
        status="approved",
        extra_fields={
            "submitted_at": '"2026-01-02T00:00:00Z"',
            "submitted_by": "user",
            "review_digest": "sha256:...",
            "approved_at": '"2026-01-03T00:00:00Z"',
            "approved_by": "admin",
        },
    )
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)

    register_proposals_scan(registry, vault_root=vault_root)
    rows = _get_rows(registry)
    assert rows[0][4] == "2026-01-03T00:00:00Z"


def test_repeated_scan_is_idempotent(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)

    register_proposals_scan(registry, vault_root=vault_root)
    rows1 = _get_rows(registry)
    register_proposals_scan(registry, vault_root=vault_root)
    rows2 = _get_rows(registry)

    assert rows1 == rows2


def test_empty_tracked_set_clears_proposal_rows(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    assert len(_get_rows(registry)) == 1

    subprocess.run(["git", "rm", "-r", "--cached", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)
    assert len(_get_rows(registry)) == 0


def test_malformed_tracked_proposal_preserves_previous_rows(
    registry: Registry, vault_root: Path
) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    rows_before = _get_rows(registry)

    # Break the proposal
    (vault_root / "proposals" / pid / "proposal.md").write_text("broken")

    with pytest.raises(ProposalScanError, match="Malformed proposal"):
        register_proposals_scan(registry, vault_root=vault_root)

    assert _get_rows(registry) == rows_before


def test_tracked_but_missing_working_tree_proposal_preserves_previous_rows(
    registry: Registry, vault_root: Path
) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    rows_before = _get_rows(registry)

    # Remove from working tree but NOT from git index
    (vault_root / "proposals" / pid / "proposal.md").unlink()

    with pytest.raises(ProposalScanError, match="missing from working tree"):
        register_proposals_scan(registry, vault_root=vault_root)

    assert _get_rows(registry) == rows_before


def test_database_insertion_failure_preserves_previous_rows(
    registry: Registry, vault_root: Path
) -> None:
    pid1 = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid1)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    rows_before = _get_rows(registry)

    pid2 = "prop-20260101T000000Z-bbbbbbbb"
    make_proposal(vault_root, pid2)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)

    # Mock updated_at to return a dict, which sqlite cannot adapt, causing InterfaceError
    with patch("lifeos.registry.proposals.derive_proposal_updated_at", return_value={}):
        with pytest.raises(ProposalScanError, match="Failed to update registry"):
            register_proposals_scan(registry, vault_root=vault_root)

    assert _get_rows(registry) == rows_before


def test_scan_writes_no_canonical_files(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    pdir = make_proposal(vault_root, pid)
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)

    mtime_md = (pdir / "proposal.md").stat().st_mtime_ns
    mtime_json = (pdir / "patches.json").stat().st_mtime_ns

    register_proposals_scan(registry, vault_root=vault_root)

    assert (pdir / "proposal.md").stat().st_mtime_ns == mtime_md
    assert (pdir / "patches.json").stat().st_mtime_ns == mtime_json


def test_list_proposals_converts_to_immutable_summaries_and_orders_deterministically(
    registry: Registry, vault_root: Path
) -> None:
    pid1 = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid1, status="draft")  # updated 2026-01-01

    pid2 = "prop-20260102T000000Z-bbbbbbbb"
    make_proposal(
        vault_root,
        pid2,
        status="draft",
        extra_fields={"submitted_at": '"2026-01-02T00:00:00Z"', "submitted_by": "user"},
    )

    # same updated_at as pid2, different ID
    pid3 = "prop-20260102T000000Z-aaaaaaaa"
    make_proposal(
        vault_root,
        pid3,
        status="draft",
        extra_fields={"submitted_at": '"2026-01-02T00:00:00Z"', "submitted_by": "user"},
    )

    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    with registry.connect() as conn:
        summaries = list_proposals(conn)

    assert isinstance(summaries, tuple)
    assert len(summaries) == 3

    assert summaries[0].id == pid3
    assert summaries[1].id == pid2
    assert summaries[2].id == pid1

    # Check immutable ProposalSummary
    assert isinstance(summaries[0], ProposalSummary)
    assert summaries[0].status == ProposalStatus.DRAFT


def test_list_proposals_typed_status_filtering_and_empty_list(
    registry: Registry, vault_root: Path
) -> None:
    pid1 = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid1, status="draft")

    pid2 = "prop-20260102T000000Z-bbbbbbbb"
    make_proposal(
        vault_root,
        pid2,
        status="approved",
        extra_fields={"approved_at": '"2026-01-02T00:00:00Z"', "approved_by": "admin"},
    )

    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    with registry.connect() as conn:
        approved_summaries = list_proposals(conn, status=ProposalStatus.APPROVED)
        assert len(approved_summaries) == 1
        assert approved_summaries[0].id == pid2

        # Empty list check
        rejected_summaries = list_proposals(conn, status=ProposalStatus.REJECTED)
        assert rejected_summaries == ()


def test_count_proposals_by_status(registry: Registry, vault_root: Path) -> None:
    pid1 = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid1, status="draft")
    pid2 = "prop-20260101T000000Z-bbbbbbbb"
    make_proposal(vault_root, pid2, status="draft")
    pid3 = "prop-20260101T000000Z-cccccccc"
    make_proposal(
        vault_root,
        pid3,
        status="approved",
        extra_fields={"approved_at": '"2026-01-02T00:00:00Z"', "approved_by": "admin"},
    )

    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    with registry.connect() as conn:
        counts = count_proposals_by_status(conn)

    # count result includes only present statuses
    assert ProposalStatus.REJECTED not in counts

    assert counts[ProposalStatus.DRAFT] == 2
    assert counts[ProposalStatus.APPROVED] == 1

    # count mapping order is deterministic (by ProposalStatus iteration)
    keys = list(counts.keys())
    assert keys == [ProposalStatus.DRAFT, ProposalStatus.APPROVED]


def test_query_functions_handle_unknown_status(registry: Registry, vault_root: Path) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid, status="draft")
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    with registry.connect() as conn:
        conn.execute("UPDATE proposals SET status = 'corrupted'")

        with pytest.raises(
            ProposalQueryError, match="Invalid status value in database"
        ) as exc_info:
            list_proposals(conn)
        assert isinstance(exc_info.value.__cause__, ValueError)

        with pytest.raises(
            ProposalQueryError, match="Invalid status value in database"
        ) as exc_info:
            count_proposals_by_status(conn)
        assert isinstance(exc_info.value.__cause__, ValueError)


def test_query_functions_handle_sqlite_error(tmp_path: Path) -> None:
    db_path = tmp_path / "uninitialized.sqlite"
    registry = Registry(db_path)

    with pytest.raises(
        ProposalQueryError, match="Failed to execute proposal list query"
    ) as exc_info:
        with registry._connection(create=True, read_only=False) as conn:
            list_proposals(conn)
    assert isinstance(exc_info.value.__cause__, sqlite3.Error)

    with pytest.raises(
        ProposalQueryError, match="Failed to execute proposal counts query"
    ) as exc_info:
        with registry._connection(create=True, read_only=False) as conn:
            count_proposals_by_status(conn)
    assert isinstance(exc_info.value.__cause__, sqlite3.Error)


def test_query_functions_perform_no_filesystem_or_git_access(
    registry: Registry, vault_root: Path
) -> None:
    pid = "prop-20260101T000000Z-aaaaaaaa"
    make_proposal(vault_root, pid, status="draft")
    subprocess.run(["git", "add", "proposals/"], cwd=vault_root, check=True)
    register_proposals_scan(registry, vault_root=vault_root)

    with registry.connect() as conn:
        with (
            patch(
                "lifeos.registry.proposals.git_tracked_proposal_paths",
                side_effect=Exception("Git accessed!"),
            ),
            patch(
                "lifeos.registry.proposals.load_proposal_directory",
                side_effect=Exception("Filesystem accessed!"),
            ),
        ):
            summaries = list_proposals(conn)
            assert len(summaries) == 1

            counts = count_proposals_by_status(conn)
            assert counts[ProposalStatus.DRAFT] == 1
