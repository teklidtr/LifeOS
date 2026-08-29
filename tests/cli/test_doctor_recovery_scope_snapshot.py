from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import collect_recovery_readiness, recovery_report_to_dict


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


def test_case_probe_walks_only_ancestor_tree_levels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    root_oid = "1" * 40
    vault_oid = "2" * 40

    monkeypatch.setattr(recovery_readiness, "_head_oid", lambda _git, _root: "a" * 40)
    monkeypatch.setattr(
        recovery_readiness,
        "_root_tree_oid",
        lambda _git, _root, _head: root_oid,
    )

    def fake_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, check, input_bytes
        args = tuple(arguments)
        calls.append(args)
        command = [git_executable, *args]
        assert args == ("ls-tree", "-z", root_oid)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                f"040000 tree {vault_oid}\tvault\0"
                f"040000 tree {'3' * 40}\tunrelated\0"
            ).encode(),
            stderr=b"",
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", fake_run_git)

    assert recovery_readiness._git_prefix_spelling("git", tmp_path, ("Vault",)) == (
        "vault",
    )
    assert calls == [("ls-tree", "-z", root_oid)]
    assert all("ls-files" not in call for call in calls)


def test_protected_git_scope_is_excluded_before_recursive_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    policy = vault / "system" / "retrieval-policy.yml"
    policy.write_text(
        "schema_version: 1\nprotected_prefixes:\n  - secrets\n",
        encoding="utf-8",
    )
    (vault / "wiki" / "visible.md").write_text("visible\n", encoding="utf-8")
    secret = vault / "secrets" / "private.md"
    secret.parent.mkdir()
    secret.write_text("private body\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    real_run_git = recovery_readiness._run_git
    calls: list[tuple[str, ...]] = []

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        args = tuple(arguments)
        calls.append(args)
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", recording_run_git)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)

    assert diagnostics["recovery.git.uncommitted_canonical"].status == "unknown"
    assert "secrets/private.md" not in rendered
    index_queries = [call for call in calls if "ls-files" in call]
    assert index_queries
    assert any(
        ":(top,exclude,literal)secrets" in call for call in index_queries
    )
    recursive_tree_queries = [
        call for call in calls if "ls-tree" in call and "-r" in call
    ]
    assert recursive_tree_queries == []
    history_queries = [call for call in calls if "rev-list" in call or "diff-tree" in call]
    assert history_queries
    assert all(
        ":(top,exclude,literal)secrets" in call for call in history_queries
    )


def test_working_tree_snapshot_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    real_snapshot = recovery_readiness._working_tree_snapshot
    calls = 0

    def unstable_snapshot(
        root: Path,
        excluded: recovery_readiness.PathExclusion,
    ) -> recovery_readiness._WorkingTreeSnapshot:
        nonlocal calls
        snapshot = real_snapshot(root, excluded)
        calls += 1
        if calls == 2:
            synthetic = recovery_readiness._FsEntry(
                "wiki/appeared.md",
                stat.S_IFREG | 0o644,
                1,
                1,
                1,
                1,
                1,
            )
            return recovery_readiness._WorkingTreeSnapshot(
                tuple(sorted((*snapshot.entries, synthetic), key=lambda item: item.path))
            )
        return snapshot

    monkeypatch.setattr(recovery_readiness, "_working_tree_snapshot", unstable_snapshot)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert calls == 2
    assert diagnostics["recovery.git.repository"].status == "unknown"
    assert "working-tree metadata changed" in diagnostics["recovery.git.repository"].summary


def test_git_executable_is_resolved_before_subprocess_cwd_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    executable = tools / "git"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(recovery_readiness.shutil, "which", lambda _name: "tools/git")

    resolved = recovery_readiness._resolve_git_executable()

    assert resolved == str(executable.resolve())
    assert Path(resolved).is_absolute()


def test_pycache_named_directory_can_contain_canonical_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    note = vault / "notes" / "__pycache__" / "important.md"
    note.parent.mkdir(parents=True)
    note.write_text("canonical note\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert "notes/__pycache__/important.md" in report.untracked_paths


def test_case_only_visible_spelling_reconciles_by_filesystem_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o644,
        st_size=7,
        st_mtime_ns=11,
        st_ctime_ns=13,
        st_dev=17,
        st_ino=19,
    )
    snapshot = recovery_readiness._WorkingTreeSnapshot(
        (
            recovery_readiness._FsEntry(
                "wiki/note.md",
                observed.st_mode,
                observed.st_size,
                observed.st_mtime_ns,
                observed.st_ctime_ns,
                observed.st_dev,
                observed.st_ino,
            ),
        )
    )
    entry = recovery_readiness._IndexEntry(
        "Wiki/note.md",
        0o100644,
        "0" * 40,
        observed.st_ctime_ns,
        observed.st_mtime_ns,
        observed.st_dev,
        observed.st_ino,
        observed.st_size,
    )
    monkeypatch.setattr(
        recovery_readiness,
        "_lstat",
        lambda _vault, _path: observed,
    )

    modified, deleted, uncertain, matched = recovery_readiness._worktree_from_snapshot(
        (entry,),
        tmp_path,
        (),
        lambda _path: False,
        snapshot,
    )

    assert modified == ()
    assert deleted == ()
    assert uncertain == ()
    assert matched == ("wiki/note.md",)


def test_reserved_lifeos_is_disposable_with_external_configured_runtime(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    runtime_file = vault / ".lifeos" / "registry.db"
    runtime_file.parent.mkdir()
    runtime_file.write_bytes(b"disposable")
    config = SimpleNamespace(
        vault_root=vault.resolve(),
        runtime_dir=(tmp_path / "external-runtime").resolve(),
    )

    report = collect_recovery_readiness(config)  # type: ignore[arg-type]
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)

    assert ".lifeos/registry.db" not in rendered
    assert all(not path.startswith(".lifeos/") for path in report.untracked_paths)


@pytest.mark.skipif(os.name == "nt", reason="Windows trims or rejects trailing-space path components")
def test_repository_root_preserves_trailing_whitespace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault "
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert report.repository_root == str(vault.resolve())
    assert _diagnostics(report)["recovery.git.repository"].status == "pass"


def test_case_insensitive_policy_alias_is_protected_without_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    policy = vault / "system" / "retrieval-policy.yml"
    policy.write_text(
        "schema_version: 1\nprotected_prefixes:\n  - secrets\n",
        encoding="utf-8",
    )
    protected = vault / "Secrets" / "new.md"
    protected.parent.mkdir()
    protected.write_text("private body\n", encoding="utf-8")
    monkeypatch.setattr(recovery_readiness, "_vault_case_insensitive", lambda _vault: True)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)
    diagnostics = _diagnostics(report)

    assert "Secrets/new.md" not in rendered
    assert report.untracked_paths == ()
    assert diagnostics["recovery.git.untracked_canonical"].status == "unknown"
    assert "protected or policy-excluded" in diagnostics[
        "recovery.git.untracked_canonical"
    ].summary


@pytest.mark.skipif(os.name == "nt", reason="Windows does not allow '*' in filenames")
def test_check_ignore_keeps_pathspec_magic_filename_literal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    filename = ":(glob)*"
    with (vault / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(":(glob)\\*\n")
    path = vault / filename
    path.write_text("ignored canonical file\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert filename in report.ignored_paths
    assert filename not in report.untracked_paths
    assert _diagnostics(report)["recovery.git.ignored_canonical"].status == "warning"
