from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch
from lifeos.registry._registry import Registry
from lifeos.proposals.schema import ProposalStatus
from lifeos.registry.proposals import ProposalSummary


from lifeos import __version__
from lifeos.cli import main


def test_help_states_application_purpose(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    captured = capsys.readouterr()
    help_text = " ".join(captured.out.split())
    assert exc_info.value.code == 0
    assert "private, Obsidian-native system" in help_text
    assert "adaptive planning" in help_text
    assert captured.err == ""


def test_version_matches_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out == f"lifeos {__version__}\n"
    assert captured.err == ""


def test_unknown_command_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["unknown"])

    captured = capsys.readouterr()
    assert exc_info.value.code != 0
    assert "invalid choice: 'unknown'" in captured.err

def test_proposals_without_list_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["proposals"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "usage:" in captured.err

def test_invalid_status_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["proposals", "list", "--status", "invalid"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "invalid choice: 'invalid'" in captured.err

@pytest.fixture
def mock_config(tmp_path: Path) -> Path:
    config_file = tmp_path / "lifeos.yml"
    config_file.write_text(f"vault_root: '{tmp_path}'\nruntime_dir: '{tmp_path}'\n")
    return tmp_path

def test_missing_database_exits_1_and_is_not_created(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    assert not db_path.exists()

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        exit_code = main(["proposals", "list"])

    assert not db_path.exists()
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Registry error" in captured.err
    assert captured.out == ""

def test_existing_database_without_proposals_table_exits_1(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    from lifeos.registry._migrations import MIGRATIONS

    with patch("lifeos.registry._registry._migration_plan", return_value=(MIGRATIONS[0],)):
        Registry(db_path).initialize()

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        exit_code = main(["proposals", "list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Query error: Proposal index unavailable" in captured.err
    assert captured.out == ""

def test_corrupted_stored_status_exits_1(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    Registry(db_path).initialize()

    with Registry(db_path).connect() as conn:
        conn.execute("INSERT INTO proposals (id, status, title, created_at, updated_at) VALUES ('id1', 'corrupt', 'Title', '2026-01-01', '2026-01-01')")

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        exit_code = main(["proposals", "list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Query error" in captured.err
    assert "Invalid status value in database" in captured.err
    assert captured.out == ""

def test_empty_result_prints_headers_only(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    Registry(db_path).initialize()

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        exit_code = main(["proposals", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == "ID  STATUS  UPDATED  TITLE\n"

def test_list_proposals_output_format_and_filtering(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    Registry(db_path).initialize()

    with Registry(db_path).connect() as conn:
        conn.executemany("INSERT INTO proposals (id, status, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", [
            ("prop-1", "draft", "Title 1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
            ("prop-long-id-2", "approved", "Title 2", "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"),
        ])

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        with patch("lifeos.registry.proposals.list_proposals") as mock_list:
            mock_list.return_value = [
                ProposalSummary("prop-long-id-2", ProposalStatus.APPROVED, "Title 2", "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"),
                ProposalSummary("prop-1", ProposalStatus.DRAFT, "Title 1", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
            ]
            exit_code = main(["proposals", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""

    # Exact column headers and deterministic spacing based on returned rows
    expected_out = (
        "ID              STATUS    UPDATED               TITLE\n"
        "prop-long-id-2  approved  2026-01-03T00:00:00Z  Title 2\n"
        "prop-1          draft     2026-01-02T00:00:00Z  Title 1\n"
    )
    assert captured.out == expected_out

    # Check filtering
    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"):
        with patch("lifeos.registry.proposals.list_proposals") as mock_list:
            mock_list.return_value = [
                ProposalSummary("prop-long-id-2", ProposalStatus.APPROVED, "Title 2", "2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"),
            ]
            exit_code = main(["proposals", "list", "--status", "approved"])

    captured = capsys.readouterr()
    assert exit_code == 0
    mock_list.assert_called_once()
    assert mock_list.call_args[1]["status"] == ProposalStatus.APPROVED

def test_command_performs_no_scan_or_file_access(capsys: pytest.CaptureFixture[str], mock_config: Path) -> None:
    db_path = mock_config / "registry.db"
    Registry(db_path).initialize()
    with Registry(db_path).connect() as conn:
        conn.execute("INSERT INTO proposals (id, status, title, created_at, updated_at) VALUES ('p1', 'draft', 'T', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")

    with patch("lifeos.cli.Path", return_value=mock_config / "lifeos.yml"), \
         patch("lifeos.registry.proposals.git_tracked_proposal_paths", side_effect=Exception("Git accessed!")), \
         patch("lifeos.registry.proposals.load_proposal_directory", side_effect=Exception("Files accessed!")), \
         patch("lifeos.registry.file_tracking.register_scan", side_effect=Exception("Scan accessed!")), \
         patch("lifeos.registry.proposals.register_proposals_scan", side_effect=Exception("Scan accessed!")):

        exit_code = main(["proposals", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "p1" in captured.out
