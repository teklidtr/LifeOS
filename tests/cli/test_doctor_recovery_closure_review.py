from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repository: Path, message: str) -> str:
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
    return _git(repository, "rev-parse", "HEAD").stdout.strip()


def _diagnostics(
    report: recovery_readiness.RecoveryReport,
) -> dict[str, recovery_readiness.RecoveryDiagnostic]:
    return {item.id: item for item in report.diagnostics}


def test_object_store_hardlink_fails_closed_before_git_reads_it(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    loose = repository / ".git" / "objects" / "aa"
    loose.mkdir()
    object_file = loose / ("0" * 38)
    object_file.write_bytes(b"protected-looking-object")
    protected_alias = tmp_path / "protected-note.md"
    os.link(object_file, protected_alias)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="hard link"):
        recovery_readiness._build_sandbox(repository)


def test_repository_info_symlink_fails_closed_before_exclude_copy(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")

    live_info = repository / ".git" / "info"
    original_info = repository / ".git" / "info-original"
    live_info.rename(original_info)
    protected_info = tmp_path / "protected-info"
    protected_info.mkdir()
    (protected_info / "exclude").write_text("secrets/private.md\n", encoding="utf-8")
    live_info.symlink_to(protected_info, target_is_directory=True)

    try:
        with pytest.raises(recovery_readiness.RecoveryGitError, match="unsafe symlink"):
            recovery_readiness._build_sandbox(repository)
    finally:
        live_info.unlink()
        original_info.rename(live_info)


def test_final_topology_check_uses_pinned_metadata_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    sandbox = recovery_readiness._build_sandbox(repository)
    assert sandbox is not None
    assert sandbox.metadata_fd_path is not None

    seen: list[Path] = []
    original = recovery_readiness._reject_split_index

    def recording_reject(path: Path) -> None:
        seen.append(path)
        original(path)

    monkeypatch.setattr(recovery_readiness, "_reject_split_index", recording_reject)
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        assert recovery_readiness._validate_sandbox_stability(sandbox) is True
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()

    assert seen == [Path(sandbox.metadata_fd_path)]


def test_check_ignore_uses_snapshotted_sources_after_live_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "wiki").mkdir()
    (repository / "wiki" / "visible.md").write_text("visible\n", encoding="utf-8")
    live_ignore = repository / ".gitignore"
    live_ignore.write_text("*.tmp\n", encoding="utf-8")
    protected = tmp_path / "protected-note.md"
    protected.write_text("wiki/visible.md\n", encoding="utf-8")

    sandbox = recovery_readiness._build_sandbox(repository)
    assert sandbox is not None
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    original_run = subprocess.run
    backup_ignore = repository / ".gitignore-original"
    swapped = False

    def racing_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal swapped
        if not swapped:
            swapped = True
            live_ignore.rename(backup_ignore)
            os.link(protected, live_ignore)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(recovery_readiness.subprocess, "run", racing_run)
    git = recovery_readiness._resolve_git_executable()
    assert git is not None
    try:
        ignored = recovery_readiness._ignored_paths(
            git,
            repository,
            ("wiki/visible.md",),
            (),
            lambda _path: False,
        )
        assert ignored == ()
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()
        if live_ignore.exists():
            live_ignore.unlink()
        if backup_ignore.exists():
            backup_ignore.rename(live_ignore)

    assert swapped is True


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_ignored_symlink_is_still_a_structural_recovery_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    with (vault / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("\nwiki/link.md\n")
    _commit_all(vault, "baseline")

    external = tmp_path / "external-note.md"
    external.write_text("external bytes\n", encoding="utf-8")
    link = vault / "wiki" / "link.md"
    link.symlink_to(external)

    report = recovery_readiness.collect_recovery_readiness(
        load_config(vault / "lifeos.yml")
    )
    diagnostics = _diagnostics(report)

    assert "wiki/link.md" in report.ignored_paths
    assert diagnostics["recovery.git.canonical_objects"].status == "failure"
    assert "wiki/link.md" in diagnostics["recovery.git.canonical_objects"].paths
