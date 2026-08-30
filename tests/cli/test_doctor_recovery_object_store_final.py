from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.entrypoint import main


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repository: Path, message: str) -> None:
    _git(repository, "add", "-A")
    _git(
        repository,
        "-c",
        "user.name=LifeOS Test",
        "-c",
        "user.email=lifeos@example.invalid",
        "commit",
        "-q",
        "-m",
        message,
    )


def test_config_snapshot_accepts_quoted_safe_core_scalars(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        "[core]\n"
        '\tfilemode = "false"\n'
        '\tignorecase = "true" # accepted Git scalar comment\n'
        '\trepositoryformatversion = "0"\n',
        encoding="utf-8",
    )

    _raw, includes, filemode, ignorecase = recovery_readiness._config_snapshot(config)

    assert includes is False
    assert filemode is False
    assert ignorecase is True


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_object_store_snapshot_pins_pack_descendants_against_path_swap(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    for index in range(20):
        (vault / "wiki" / f"note-{index}.md").write_text(
            f"baseline {index}\n" * 50,
            encoding="utf-8",
        )
    _commit_all(vault, "baseline")
    _git(vault, "gc", "--prune=now")

    live_pack = vault / ".git" / "objects" / "pack"
    assert any(live_pack.glob("*.pack"))
    sandbox = recovery_readiness._build_sandbox(vault)
    assert sandbox is not None
    assert sandbox.object_fds
    assert sandbox.object_fd_path is not None

    original_pack = vault / ".git" / "objects" / "pack-original"
    redirected = tmp_path / "protected-pack-target"
    redirected.mkdir()

    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        live_pack.rename(original_pack)
        live_pack.symlink_to(redirected, target_is_directory=True)

        git = recovery_readiness._resolve_git_executable()
        assert git is not None
        result = recovery_readiness._run_git(
            git,
            cwd=vault,
            arguments=("cat-file", "-t", "HEAD"),
        )

        assert result.stdout.strip() == b"commit"
        assert sandbox.object_fd_path != str(vault / ".git" / "objects")
    finally:
        if live_pack.is_symlink():
            live_pack.unlink()
        if original_pack.exists():
            original_pack.rename(live_pack)
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_object_store_snapshot_rejects_preexisting_pack_indirection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")
    _git(vault, "gc", "--prune=now")

    live_pack = vault / ".git" / "objects" / "pack"
    original_pack = vault / ".git" / "objects" / "pack-original"
    live_pack.rename(original_pack)
    live_pack.symlink_to(original_pack, target_is_directory=True)
    try:
        with pytest.raises(recovery_readiness.RecoveryGitError, match="symlink"):
            recovery_readiness._build_sandbox(vault)
    finally:
        live_pack.unlink()
        original_pack.rename(live_pack)
