from pathlib import Path
import subprocess
import pytest
from lifeos.scanner.git import git_tracked_proposal_paths, GitScannerError

def test_git_tracked_proposal_paths(tmp_path: Path) -> None:
    # Initialize a real git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    # Tracked canonical proposal 1
    p1_dir = tmp_path / "proposals" / "prop-20260101T000000Z-aaaaaaaa"
    p1_dir.mkdir(parents=True)
    p1_file = p1_dir / "proposal.md"
    p1_file.write_text("content")
    subprocess.run(["git", "add", "proposals/prop-20260101T000000Z-aaaaaaaa/proposal.md"], cwd=tmp_path, check=True)

    # Tracked canonical proposal 2 (should be sorted after p1)
    p2_dir = tmp_path / "proposals" / "prop-20260102T000000Z-bbbbbbbb"
    p2_dir.mkdir(parents=True)
    p2_file = p2_dir / "proposal.md"
    p2_file.write_text("content")
    subprocess.run(["git", "add", "proposals/prop-20260102T000000Z-bbbbbbbb/proposal.md"], cwd=tmp_path, check=True)

    # Untracked canonical proposal
    p3_dir = tmp_path / "proposals" / "prop-20260103T000000Z-cccccccc"
    p3_dir.mkdir(parents=True)
    p3_file = p3_dir / "proposal.md"
    p3_file.write_text("content")
    # Not added to git!

    # Tracked noncanonical Markdown
    p4_dir = tmp_path / "proposals" / "prop-20260104T000000Z-dddddddd"
    p4_dir.mkdir(parents=True)
    p4_file = p4_dir / "readme.md"
    p4_file.write_text("content")
    subprocess.run(["git", "add", "proposals/prop-20260104T000000Z-dddddddd/readme.md"], cwd=tmp_path, check=True)

    # Also tracked random file under proposals
    p5_file = tmp_path / "proposals" / "random.md"
    p5_file.write_text("content")
    subprocess.run(["git", "add", "proposals/random.md"], cwd=tmp_path, check=True)

    paths = git_tracked_proposal_paths(tmp_path)

    # Assert deterministic ordering and expected filtering
    assert len(paths) == 2
    assert paths[0] == Path("proposals/prop-20260101T000000Z-aaaaaaaa/proposal.md")
    assert paths[1] == Path("proposals/prop-20260102T000000Z-bbbbbbbb/proposal.md")

def test_git_failure_produces_stable_error(tmp_path: Path) -> None:
    # Not a git repository
    with pytest.raises(GitScannerError, match="Git execution failed"):
        git_tracked_proposal_paths(tmp_path)
