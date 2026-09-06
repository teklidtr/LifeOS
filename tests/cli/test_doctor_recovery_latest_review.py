from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.retrieval.contracts import RetrievalPolicy, RetrievalScope
from lifeos.runtime_scope import build_runtime_exclusion_matcher


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


def test_runtime_scope_excludes_whitespace_named_descendants(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = vault / ".lifeos"
    runtime.mkdir(parents=True)
    matcher = build_runtime_exclusion_matcher(
        vault,
        runtime_dir=runtime,
        snapshot_prefix=".lifeos",
    )

    assert matcher(".lifeos/cache/report .md") is True
    assert matcher(".lifeos/ cache /note.md") is True
    assert matcher(" .lifeos/cache/report .md") is False


def test_config_snapshot_recognizes_commented_include_header(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        "[core]\n\tfilemode = true\n[include] # local settings\n\tpath = ../unsafe.conf\n",
        encoding="utf-8",
    )

    _raw, includes, filemode, ignorecase = recovery_readiness._config_snapshot(config)

    assert includes is True
    assert filemode is True
    assert ignorecase is False


def test_config_snapshot_recognizes_escaped_includeif_subsection(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        '[core]\n\tfilemode = true\n[includeIf "gitdir:foo\\"bar"]\n\tpath = ../unsafe.conf\n',
        encoding="utf-8",
    )

    _raw, includes, filemode, ignorecase = recovery_readiness._config_snapshot(config)

    assert includes is True
    assert filemode is True
    assert ignorecase is False


def test_config_snapshot_fails_closed_on_unrecognized_section_header(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        '[core]\n\tfilemode = true\n[includeIf "unterminated]\n\tpath = ../unsafe.conf\n',
        encoding="utf-8",
    )

    with pytest.raises(recovery_readiness.RecoveryGitError, match="section header"):
        recovery_readiness._config_snapshot(config)


def test_metadata_tree_rejects_symlink_swap_before_descending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = tmp_path / "refs"
    heads = refs / "heads"
    heads.mkdir(parents=True)
    (heads / "main").write_text("0123456789abcdef\n", encoding="utf-8")
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "secret.md").write_text("must-not-copy\n", encoding="utf-8")
    destination = tmp_path / "snapshot"

    original_open = os.open
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "heads" and dir_fd is not None and not swapped:
            swapped = True
            heads.rename(refs / "heads-original")
            (refs / "heads").symlink_to(protected, target_is_directory=True)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(recovery_readiness.os, "open", racing_open)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="metadata entry safely"):
        recovery_readiness._copy_metadata_tree(refs, destination)

    assert swapped is True
    assert not (destination / "heads" / "secret.md").exists()


def test_repository_core_excludes_file_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_text(
        "[core]\n\texcludesFile = ../ignore-rules\n",
        encoding="utf-8",
    )

    with pytest.raises(recovery_readiness.RecoveryGitError, match="excludesFile"):
        recovery_readiness._config_snapshot(config)


def test_committed_tree_query_applies_authorized_exclusions_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "wiki").mkdir()
    (repository / "wiki" / "visible.md").write_text("visible\n", encoding="utf-8")
    (repository / "secrets").mkdir()
    (repository / "secrets" / "private.md").write_text("private\n", encoding="utf-8")
    head = _commit_all(repository, "baseline")

    context = SimpleNamespace(prefix=(), case_insensitive_prefix=False)
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(protected_prefixes=("secrets",)),
        RetrievalScope(),
        case_insensitive=False,
    )
    config = SimpleNamespace(
        vault_root=repository,
        runtime_dir=repository / ".lifeos",
    )
    pathspecs = recovery_readiness._authorized_git_pathspecs(context, scope, config)
    seen_outputs: list[bytes] = []
    seen_arguments: list[tuple[str, ...]] = []
    original_run_git = recovery_readiness._run_git

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: Any,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        result = original_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )
        normalized = tuple(arguments)
        if "ls-files" in normalized or "diff-index" in normalized:
            seen_arguments.append(normalized)
            seen_outputs.append(result.stdout)
        assert "ls-tree" not in normalized
        return result

    monkeypatch.setattr(recovery_readiness, "_run_git", recording_run_git)
    git = recovery_readiness._resolve_git_executable()
    assert git is not None

    entries = recovery_readiness._tree_entries(
        git,
        repository,
        head,
        pathspecs,
        (),
        scope,
    )

    assert "wiki/visible.md" in entries
    assert "secrets/private.md" not in entries
    assert seen_outputs
    assert all(b"secrets/private.md" not in output for output in seen_outputs)
    assert any(":(top,exclude,literal)secrets" in arguments for arguments in seen_arguments)
