from __future__ import annotations

import json
import os
import subprocess
import zlib
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


def test_recovery_verifies_committed_blob_payload_integrity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    corrupt = vault / "wiki" / "corrupt.md"
    corrupt.write_text("header\n" + ("A" * 200_000) + "\nfooter\n", encoding="utf-8")
    _commit_all(vault, "commit payload")

    object_id = _git(vault, "rev-parse", "HEAD:wiki/corrupt.md").stdout.strip()
    object_path = vault / ".git" / "objects" / object_id[:2] / object_id[2:]
    assert object_path.is_file(), "test requires the freshly committed blob to remain loose"
    original = bytearray(object_path.read_bytes())
    assert original
    os.chmod(object_path, 0o644)
    original[-1] ^= 0x01
    object_path.write_bytes(original)

    batch_check = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=vault,
        input=f"{object_id}\n",
        check=True,
        capture_output=True,
        text=True,
    )
    assert batch_check.stdout.strip() == f"{object_id} blob"

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostic = _diagnostic(report, "recovery.git.canonical_objects")

    assert "wiki/corrupt.md" in report.unrecoverable_committed_paths
    assert getattr(diagnostic, "status") == "failure"
    assert getattr(diagnostic, "severity") == "error"


def test_recovery_verifies_blob_payload_hash_matches_expected_oid(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    note = vault / "wiki" / "hash-mismatch.md"
    note.write_text("original canonical body\n", encoding="utf-8")
    _commit_all(vault, "hash baseline")

    object_id = _git(vault, "rev-parse", "HEAD:wiki/hash-mismatch.md").stdout.strip()
    object_path = vault / ".git" / "objects" / object_id[:2] / object_id[2:]
    assert object_path.is_file(), "test requires the freshly committed blob to remain loose"

    replacement = b"different but well-formed blob payload\n"
    encoded = zlib.compress(f"blob {len(replacement)}\0".encode("ascii") + replacement)
    os.chmod(object_path, 0o644)
    object_path.write_bytes(encoded)

    cat_file = subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=vault,
        check=False,
        capture_output=True,
    )
    assert cat_file.returncode == 0
    assert cat_file.stdout == replacement

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostic = _diagnostic(report, "recovery.git.canonical_objects")

    assert "wiki/hash-mismatch.md" in report.unrecoverable_committed_paths
    assert getattr(diagnostic, "status") == "failure"


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
        if args == ("ls-files", "-z"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=b"vault/wiki/note.md\0outside.txt\0",
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

    context = recovery_readiness._repo_context("git", vault)

    assert context is not None
    assert context.prefix == ("vault",)
    assert context.pathspec == "vault"
    assert context.case_insensitive_prefix is True
    assert recovery_readiness._canonical_path(
        "Vault/wiki/note.md",
        context.prefix,
        lambda path: False,
        case_insensitive_prefix=context.case_insensitive_prefix,
    ) == "wiki/note.md"
    assert recovery_readiness._canonical_path(
        "outside.txt",
        context.prefix,
        lambda path: False,
        case_insensitive_prefix=context.case_insensitive_prefix,
    ) is None


def test_git_path_query_warning_fails_closed_as_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            stderr=b"warning: could not open directory 'locked/': Permission denied\n",
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", fake_run_git)

    with pytest.raises(recovery_readiness.RecoveryGitError, match="incomplete traversal"):
        recovery_readiness._git_paths(
            "git",
            tmp_path,
            ("ls-files", "--others", "--exclude-standard", "-z", "--", "."),
            (),
            lambda path: False,
        )
