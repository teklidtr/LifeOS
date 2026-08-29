from __future__ import annotations

import shlex
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import collect_recovery_readiness


def _git(
    repository: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _commit_index(repository: Path, message: str) -> str:
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


def _commit_all(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    return _commit_index(repository, message)


def _diagnostics(
    report: recovery_readiness.RecoveryReport,
) -> dict[str, recovery_readiness.RecoveryDiagnostic]:
    return {item.id: item for item in report.diagnostics}


def test_recovery_ignores_inherited_repository_selection_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "inside.md").write_text("inside\n", encoding="utf-8")
    _commit_all(vault, "vault baseline")

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _git(unrelated, "init", "-q")
    (unrelated / "wiki").mkdir()
    (unrelated / "wiki" / "leak.md").write_text("unrelated\n", encoding="utf-8")
    _commit_all(unrelated, "unrelated baseline")

    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(unrelated))
    monkeypatch.setenv("GIT_INDEX_FILE", str(unrelated / ".git" / "index"))
    monkeypatch.setenv("GIT_TRACE", str(tmp_path / "unexpected-trace"))

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert report.repository_root == str(vault.resolve())
    assert report.committed_canonical_count > 0
    serialized_paths = {
        *report.uncommitted_paths,
        *report.staged_paths,
        *report.unstaged_paths,
        *report.deleted_paths,
        *report.untracked_paths,
        *report.ignored_paths,
        *report.index_flagged_paths,
        *report.unrecoverable_committed_paths,
    }
    assert "wiki/leak.md" not in serialized_paths
    assert not (tmp_path / "unexpected-trace").exists()


def test_recovery_repository_discovery_failure_is_unknown_without_stderr_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    real_run_git = recovery_readiness._run_git

    def fake_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        if tuple(arguments) == ("rev-parse", "--show-toplevel"):
            command = [git_executable, *arguments]
            return subprocess.CompletedProcess(
                command,
                128,
                stdout=b"",
                stderr=b"fatal: detected dubious ownership in private/repository\n",
            )
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", fake_run_git)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)
    summary = diagnostics["recovery.git.repository"].summary

    assert diagnostics["recovery.git.repository"].status == "unknown"
    assert "dubious ownership" not in summary
    assert "private/repository" not in summary
    assert "could not be verified safely" in summary
    assert report.repository_root is None


def test_recovery_index_flags_prevent_false_clean_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    assume = vault / "wiki" / "assume.md"
    skipped = vault / "wiki" / "skip.md"
    assume_before = b"assume-before\n"
    assume_after = b"assume-after!\n"
    skip_before = b"skip-before\n"
    skip_after = b"skip-after!\n"
    assert len(assume_before) == len(assume_after)
    assert len(skip_before) == len(skip_after)
    assume.write_bytes(assume_before)
    skipped.write_bytes(skip_before)
    _commit_all(vault, "flag baseline")

    _git(vault, "update-index", "--assume-unchanged", "wiki/assume.md")
    _git(vault, "update-index", "--skip-worktree", "wiki/skip.md")
    assume.write_bytes(assume_after)
    skipped.write_bytes(skip_after)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert set(report.index_flagged_paths) == {"wiki/assume.md", "wiki/skip.md"}
    assert diagnostics["recovery.git.uncommitted_canonical"].status == "unknown"
    assert set(diagnostics["recovery.git.uncommitted_canonical"].paths) >= {
        "wiki/assume.md",
        "wiki/skip.md",
    }


def test_recovery_detects_unstaged_metadata_without_running_clean_filter(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    marker = tmp_path / "clean-filter-called"
    filter_script = tmp_path / "clean-filter.sh"
    filter_script.write_text(
        "#!/bin/sh\n"
        f"touch {shlex.quote(str(marker))}\n"
        "cat\n",
        encoding="utf-8",
    )
    filter_script.chmod(0o755)
    _git(vault, "config", "filter.lifeos-test.clean", str(filter_script))

    attributes = vault / ".gitattributes"
    attributes.write_text("wiki/private.md filter=lifeos-test\n", encoding="utf-8")
    note = vault / "wiki" / "private.md"
    note.write_text("before canonical body\n", encoding="utf-8")
    _commit_all(vault, "filter baseline")
    marker.unlink(missing_ok=True)

    changed_bytes = b"after canonical body with a different size\n"
    note.write_bytes(changed_bytes)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert not marker.exists()
    assert note.read_bytes() == changed_bytes
    assert "wiki/private.md" in report.unstaged_paths
    assert "wiki/private.md" in report.uncommitted_paths
    assert diagnostics["recovery.git.uncommitted_canonical"].status == "warning"


def test_recovery_staged_state_avoids_git_diff_subsystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")
    staged = vault / "wiki" / "staged.md"
    staged.write_text("staged\n", encoding="utf-8")
    _git(vault, "add", "wiki/staged.md")
    _git(vault, "config", "diff.renames", "true")
    _git(vault, "config", "diff.orderFile", "secrets/order-file")

    real_run_git = recovery_readiness._run_git
    diff_queries: list[tuple[str, ...]] = []

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        args = tuple(arguments)
        if args and args[0] == "diff":
            diff_queries.append(args)
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", recording_run_git)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert diff_queries == []
    assert "wiki/staged.md" in report.staged_paths


def test_recovery_treats_missing_blob_payload_integrity_as_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    note = vault / "wiki" / "missing-object.md"
    note.write_text("unique missing blob payload\n", encoding="utf-8")
    _commit_all(vault, "blob baseline")
    object_id = _git(vault, "rev-parse", "HEAD:wiki/missing-object.md").stdout.strip()
    object_path = vault / ".git" / "objects" / object_id[:2] / object_id[2:]
    assert object_path.exists()
    object_path.unlink()

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert diagnostics["recovery.git.canonical_objects"].status == "unknown"
    assert report.unrecoverable_committed_paths == ()
    assert report.committed_canonical_count > 0


def test_recovery_reports_gitlink_as_unrecoverable_canonical_entry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    seed = vault / "wiki" / "seed.md"
    seed.write_text("seed\n", encoding="utf-8")
    baseline = _commit_all(vault, "gitlink baseline")
    _git(
        vault,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{baseline},wiki/external",
    )
    _commit_index(vault, "commit canonical gitlink")
    (vault / "wiki" / "external").mkdir()

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert diagnostics["recovery.git.canonical_objects"].status == "failure"
    assert "wiki/external" in report.unrecoverable_committed_paths
    assert "wiki/external" in diagnostics["recovery.git.canonical_objects"].paths


def test_recovery_git_environment_clears_inherited_config_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "/tmp/evil-fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "core.pager")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "evil-pager")
    monkeypatch.setenv("GIT_DIR", "/tmp/unrelated.git")
    monkeypatch.setenv("GIT_TRACE_PACKET", "/tmp/trace")

    env = recovery_readiness._git_environment()

    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
    assert env["GIT_CONFIG_VALUE_0"] == "false"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == recovery_readiness.os.devnull
    assert "GIT_CONFIG_KEY_1" not in env
    assert "GIT_CONFIG_VALUE_1" not in env
    assert "GIT_DIR" not in env
    assert "GIT_TRACE_PACKET" not in env
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_recovery_skips_ignore_traversal_when_protected_scope_exists(
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
    _commit_all(vault, "baseline")
    protected = vault / "secrets"
    protected.mkdir()
    (protected / ".gitignore").write_text("*.md\n", encoding="utf-8")
    (protected / "private.md").write_text("private\n", encoding="utf-8")

    real_run_git = recovery_readiness._run_git
    ignore_queries: list[tuple[str, ...]] = []

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        args = tuple(arguments)
        if args and args[0] == "ls-files" and "--exclude-standard" in args:
            ignore_queries.append(args)
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

    assert ignore_queries == []
    assert report.untracked_paths == ()
    assert report.ignored_paths == ()
    assert diagnostics["recovery.git.untracked_canonical"].status == "unknown"
    assert diagnostics["recovery.git.ignored_canonical"].status == "unknown"


def test_recovery_returns_unknown_if_head_or_index_changes_during_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    real_snapshot = recovery_readiness._git_snapshot
    calls = 0

    def unstable_snapshot(git: str, root: Path, pathspec: str) -> recovery_readiness._GitSnapshot:
        nonlocal calls
        snapshot = real_snapshot(git, root, pathspec)
        calls += 1
        if calls == 2:
            return recovery_readiness._GitSnapshot(
                snapshot.head_oid,
                snapshot.index_debug + b"changed-after-collection",
                snapshot.index_flags,
            )
        return snapshot

    monkeypatch.setattr(recovery_readiness, "_git_snapshot", unstable_snapshot)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = _diagnostics(report)

    assert calls == 2
    assert diagnostics["recovery.git.repository"].status == "unknown"
    assert diagnostics["recovery.git.uncommitted_canonical"].status == "unknown"
    assert "changed during recovery inspection" in diagnostics["recovery.git.repository"].summary


def test_recovery_large_index_size_is_uncertain_not_modified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = recovery_readiness._IndexEntry(
        path="wiki/huge.bin",
        mode=0o100644,
        oid="0" * 40,
        ctime_ns=1,
        mtime_ns=1,
        device=0,
        inode=0,
        size=7,
    )
    observed = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o644,
        st_size=(1 << 32) + 7,
        st_mtime_ns=1,
        st_ctime_ns=1,
        st_dev=0,
        st_ino=0,
    )
    monkeypatch.setattr(recovery_readiness, "_lstat", lambda _vault, _path: observed)

    modified, deleted, uncertain = recovery_readiness._worktree_from_entries(
        (entry,),
        tmp_path,
        (),
        lambda _path: False,
    )

    assert modified == ()
    assert deleted == ()
    assert uncertain == ("wiki/huge.bin",)
