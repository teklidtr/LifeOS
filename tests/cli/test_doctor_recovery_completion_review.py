from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_metadata_root_remains_pinned_after_live_marker_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")

    protected = tmp_path / "protected-git"
    (protected / "objects").mkdir(parents=True)
    (protected / "refs").mkdir()
    (protected / "config").write_text(
        "[extensions]\n\tobjectFormat = sha256\n",
        encoding="utf-8",
    )

    live_git = repository / ".git"
    original_git = repository / ".git-original"
    original_discover = recovery_readiness._discover_pinned_git_directory
    swapped = False

    def racing_discover(vault: Path) -> object:
        nonlocal swapped
        discovered = original_discover(vault)
        assert discovered is not None
        if not swapped:
            swapped = True
            live_git.rename(original_git)
            live_git.symlink_to(protected, target_is_directory=True)
        return discovered

    monkeypatch.setattr(
        recovery_readiness,
        "_discover_pinned_git_directory",
        racing_discover,
    )

    sandbox = None
    try:
        sandbox = recovery_readiness._build_sandbox(repository)
        assert sandbox is not None
        assert sandbox.metadata_fd is not None
        assert sandbox.contains_includes is False
    finally:
        if sandbox is not None:
            sandbox.close()
        if live_git.is_symlink():
            live_git.unlink()
        if original_git.exists():
            original_git.rename(live_git)

    assert swapped is True


def test_object_store_snapshot_uses_bounded_descriptors(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    loose = repository / ".git" / "objects" / "aa"
    loose.mkdir()
    for index in range(400):
        (loose / f"{index:038x}").write_bytes(f"object-{index}".encode())

    sandbox = recovery_readiness._build_sandbox(repository)
    assert sandbox is not None
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        assert sandbox.metadata_fd is not None
        assert sandbox.object_fd is not None
        assert len(sandbox.object_fds) == 1
        assert len(recovery_readiness._sandbox_pass_fds()) <= 2
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()

    assert (loose / f"{0:038x}").stat().st_nlink == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO entries are unavailable")
def test_fifo_gitignore_fails_closed_before_git_can_block(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "wiki").mkdir()
    (repository / "wiki" / "draft.md").write_text("draft\n", encoding="utf-8")
    os.mkfifo(repository / ".gitignore")
    git = recovery_readiness._resolve_git_executable()
    assert git is not None

    with pytest.raises(recovery_readiness.RecoveryGitError, match="ignore metadata"):
        recovery_readiness._ignored_paths(
            git,
            repository,
            ("wiki/draft.md",),
            (),
            lambda _path: False,
        )


def test_ignore_query_has_bounded_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / ".gitignore").write_text("wiki/*.md\n", encoding="utf-8")
    git = recovery_readiness._resolve_git_executable()
    assert git is not None

    def timeout_run(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=[git, "check-ignore"], timeout=10)

    monkeypatch.setattr(recovery_readiness.subprocess, "run", timeout_run)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="safe time bound"):
        recovery_readiness._ignored_paths(
            git,
            repository,
            ("wiki/draft.md",),
            (),
            lambda _path: False,
        )
