from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import (
    RecoveryReport,
    collect_recovery_readiness,
    format_recovery_text,
    recovery_report_to_dict,
)


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


def _diagnostic(report: RecoveryReport, diagnostic_id: str) -> object:
    return next(item for item in report.diagnostics if item.id == diagnostic_id)


def test_recovery_includes_hidden_canonical_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    hidden = vault / ".private" / "note.md"
    hidden.parent.mkdir()
    hidden.write_text("hidden canonical note\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert ".private/note.md" in report.untracked_paths
    diagnostic = _diagnostic(report, "recovery.git.untracked_canonical")
    assert getattr(diagnostic, "status") == "warning"
    assert all(not path.startswith(".lifeos/") for path in report.untracked_paths)


def test_recovery_applies_retrieval_policy_without_false_clean_status(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0

    policy = vault / "system" / "retrieval-policy.yml"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        "schema_version: 1\n"
        "excluded_prefixes:\n"
        "  - excluded-area\n"
        "protected_prefixes:\n"
        "  - secrets\n"
        "  - journal/private\n",
        encoding="utf-8",
    )
    with (vault / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("excluded-area/\n")

    visible = vault / "wiki" / "visible.md"
    visible.write_text("visible\n", encoding="utf-8")
    protected_tracked = vault / "journal" / "private" / "tracked.md"
    protected_tracked.parent.mkdir(parents=True, exist_ok=True)
    protected_tracked.write_text("private baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    protected_tracked.write_text("private changed\n", encoding="utf-8")
    protected_untracked = vault / "secrets" / "new.md"
    protected_untracked.parent.mkdir(parents=True, exist_ok=True)
    protected_untracked.write_text("private untracked\n", encoding="utf-8")
    excluded_ignored = vault / "excluded-area" / "ignored.md"
    excluded_ignored.parent.mkdir(parents=True, exist_ok=True)
    excluded_ignored.write_text("excluded ignored\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    serialized = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)
    human = "\n".join(format_recovery_text(report))

    assert report.uncommitted_paths == ()
    assert report.untracked_paths == ()
    assert report.ignored_paths == ()
    for diagnostic_id in (
        "recovery.git.last_canonical_commit",
        "recovery.git.canonical_objects",
        "recovery.git.uncommitted_canonical",
        "recovery.git.untracked_canonical",
        "recovery.git.ignored_canonical",
    ):
        diagnostic = _diagnostic(report, diagnostic_id)
        assert getattr(diagnostic, "status") == "unknown"
        assert "protected or policy-excluded" in getattr(diagnostic, "summary")

    for private_path in (
        "journal/private/tracked.md",
        "secrets/new.md",
        "excluded-area/ignored.md",
    ):
        assert private_path not in serialized
        assert private_path not in human


@pytest.mark.skipif(os.name == "nt", reason="POSIX filenames can contain newline and ESC bytes")
def test_recovery_human_output_escapes_terminal_control_characters(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    relative_path = "wiki/line\nbreak\x1b[31m.md"
    path = vault / relative_path
    path.write_text("control-name note\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    human = "\n".join(format_recovery_text(report))

    assert relative_path in report.untracked_paths
    assert "\x1b" not in human
    assert "line\\nbreak" in human
    assert "\\u001b[31m.md" in human


def test_recovery_treats_stat_only_drift_as_unknown_not_modified(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    note = vault / "wiki" / "touched.md"
    note.write_text("unchanged canonical bytes\n", encoding="utf-8")
    _commit_all(vault, "touch baseline")

    before = note.stat()
    os.utime(note, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostic = _diagnostic(report, "recovery.git.uncommitted_canonical")

    assert "wiki/touched.md" not in report.unstaged_paths
    assert "wiki/touched.md" not in report.uncommitted_paths
    assert "wiki/touched.md" in report.working_tree_uncertain_paths
    assert getattr(diagnostic, "status") == "unknown"
    assert "wiki/touched.md" in getattr(diagnostic, "paths")


def test_recovery_does_not_inflate_committed_note_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    note = vault / "wiki" / "private.md"
    note.write_text("canonical body must stay unread by doctor\n", encoding="utf-8")
    _commit_all(vault, "metadata-only baseline")

    real_popen = subprocess.Popen
    forbidden: list[tuple[str, ...]] = []

    def guarded_popen(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        normalized = tuple(str(part) for part in command)
        if "cat-file" in normalized or "hash-object" in normalized:
            forbidden.append(normalized)
            raise AssertionError("recovery diagnostics must not read committed payloads")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(recovery_readiness.subprocess, "Popen", guarded_popen)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostic = _diagnostic(report, "recovery.git.canonical_objects")

    assert forbidden == []
    assert report.committed_canonical_count > 0
    assert getattr(diagnostic, "status") == "unknown"
    assert "do not read canonical note bodies" in getattr(diagnostic, "summary")


def test_case_insensitive_nested_prefix_uses_git_casing_without_widening_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    vault = repository / "Vault"
    vault.mkdir(parents=True)

    real_run_git = recovery_readiness._run_git

    def fake_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        args = tuple(arguments)
        command = [git_executable, *args]
        if args == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{repository}\n".encode(),
                stderr=b"",
            )
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", fake_run_git)
    monkeypatch.setattr(
        recovery_readiness,
        "_filesystem_case_insensitive",
        lambda root, relative: True,
    )
    monkeypatch.setattr(
        recovery_readiness,
        "_git_prefix_spelling",
        lambda _git, _root, _prefix: ("vault",),
    )

    context = recovery_readiness._repo_context("git", vault)

    assert context is not None
    assert context.prefix == ("vault",)
    assert context.pathspec == "vault"
    assert context.case_insensitive_prefix is True
    assert (
        recovery_readiness._canonical_path(
            "Vault/wiki/note.md",
            context.prefix,
            lambda path: False,
            case_insensitive_prefix=context.case_insensitive_prefix,
        )
        == "wiki/note.md"
    )
    assert (
        recovery_readiness._canonical_path(
            "outside.txt",
            context.prefix,
            lambda path: False,
            case_insensitive_prefix=context.case_insensitive_prefix,
        )
        is None
    )


def test_git_path_query_warning_fails_closed_without_leaking_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_warning = "warning: could not open directory 'secrets/private/': Permission denied"

    def fake_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        command = [git_executable, *arguments]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b"",
            stderr=f"{private_warning}\n".encode(),
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", fake_run_git)

    with pytest.raises(recovery_readiness.RecoveryGitError) as error:
        recovery_readiness._git_paths(
            "git",
            tmp_path,
            ("ls-files", "--others", "--exclude-standard", "-z", "--", "."),
            (),
            lambda path: False,
        )

    message = str(error.value)
    diagnostics = recovery_readiness._git_unknown(message)
    rendered = json.dumps(
        [
            {
                "id": item.id,
                "status": item.status,
                "summary": item.summary,
                "remediation": item.remediation,
            }
            for item in diagnostics
        ],
        ensure_ascii=True,
    )

    assert "incomplete results" in message
    assert private_warning not in message
    assert "secrets/private" not in message
    assert private_warning not in rendered
    assert "secrets/private" not in rendered


def test_latest_commit_diff_tree_disables_rename_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    real_run_git = recovery_readiness._run_git
    history_queries: list[tuple[str, ...]] = []

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: tuple[str, ...] | list[str],
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        args = tuple(arguments)
        if "diff-tree" in args:
            history_queries.append(args)
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", recording_run_git)

    collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert history_queries
    assert all("--no-renames" in args for args in history_queries)
