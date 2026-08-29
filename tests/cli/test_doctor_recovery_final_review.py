from __future__ import annotations

import json
import os
import stat
import subprocess
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

import lifeos.recovery_readiness as recovery_readiness
from lifeos.config import load_config
from lifeos.entrypoint import main
from lifeos.recovery_readiness import collect_recovery_readiness, recovery_report_to_dict
from lifeos.retrieval.contracts import RetrievalPolicy, RetrievalScope


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


def _diagnostics(report: recovery_readiness.RecoveryReport) -> dict[str, recovery_readiness.RecoveryDiagnostic]:
    return {item.id: item for item in report.diagnostics}


def test_git_metadata_sandbox_ignores_repository_include_added_after_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "note.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    sandbox = recovery_readiness._build_sandbox(vault)
    assert sandbox is not None
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        protected = vault / "secrets" / "invalid.conf"
        protected.parent.mkdir()
        protected.write_text("[broken\n", encoding="utf-8")
        with (vault / ".git" / "config").open("a", encoding="utf-8") as handle:
            handle.write("\n[include]\n\tpath = ../secrets/invalid.conf\n")

        result = recovery_readiness._run_git(
            recovery_readiness._resolve_git_executable(),
            cwd=vault,
            arguments=("rev-parse", "--show-toplevel"),
            check=False,
        )

        assert result.returncode == 0
        assert result.stderr == b""
        assert result.stdout.decode().rstrip("\n") == str(vault.resolve())
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


def test_positive_nested_vault_pathspec_uses_icase_when_filesystem_requires_it() -> None:
    context = SimpleNamespace(prefix=("vault",), case_insensitive_prefix=True)
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(protected_prefixes=()),
        RetrievalScope(),
        case_insensitive=True,
    )
    config = SimpleNamespace(vault_root=Path("/vault"), runtime_dir=Path("/vault/.lifeos"))

    pathspecs = recovery_readiness._authorized_git_pathspecs(context, scope, config)

    assert pathspecs[0] == ":(top,icase,literal)vault"


def test_case_sensitive_policy_does_not_hide_distinct_case_path() -> None:
    scope = recovery_readiness._ScopeFilter(
        lambda _path: False,
        RetrievalPolicy(),
        RetrievalScope(),
        case_insensitive=False,
    )

    assert scope("Private/note.md") is False
    assert scope.incomplete is False
    assert scope("private/note.md") is True
    assert scope.incomplete is True


def test_unicode_normalized_filesystem_spelling_reconciles_by_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nfc = "wiki/caf\N{LATIN SMALL LETTER E WITH ACUTE}.md"
    nfd = unicodedata.normalize("NFD", nfc)
    observed = SimpleNamespace(st_dev=17, st_ino=19)
    snapshot = recovery_readiness._WorkingTreeSnapshot(
        (
            recovery_readiness._FsEntry(
                nfd,
                stat.S_IFREG | 0o644,
                7,
                11,
                13,
                observed.st_dev,
                observed.st_ino,
            ),
        )
    )
    monkeypatch.setattr(recovery_readiness, "_lstat", lambda _vault, _path: observed)

    matched = recovery_readiness._snapshot_entry_for_index_path(tmp_path, nfc, snapshot)

    assert matched is not None
    assert matched.path == nfd


def test_racily_clean_index_entry_is_metadata_uncertain(tmp_path: Path) -> None:
    entry = recovery_readiness._IndexEntry(
        "wiki/note.md",
        0o100644,
        "0" * 40,
        100,
        200,
        17,
        19,
        7,
    )
    observed = recovery_readiness._FsEntry(
        "wiki/note.md",
        stat.S_IFREG | 0o644,
        7,
        200,
        100,
        17,
        19,
    )
    temporary = recovery_readiness.tempfile.TemporaryDirectory(prefix="lifeos-racy-test-")
    sandbox = recovery_readiness._GitMetadataSandbox(
        temporary,
        tmp_path,
        tmp_path,
        tmp_path,
        200,
        "fingerprint",
        False,
    )
    token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        assert recovery_readiness._compare_index_entry(entry, observed) == "uncertain"
    finally:
        recovery_readiness._ACTIVE_SANDBOX.reset(token)
        sandbox.close()


def test_deleted_protected_history_marks_latest_commit_evidence_incomplete(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\nprotected_prefixes:\n  - secrets\n",
        encoding="utf-8",
    )
    (vault / "wiki" / "visible.md").write_text("visible\n", encoding="utf-8")
    protected = vault / "secrets" / "private.md"
    protected.parent.mkdir()
    protected.write_text("private\n", encoding="utf-8")
    _commit_all(vault, "with protected history")
    protected.unlink()
    protected.parent.rmdir()
    _commit_all(vault, "delete protected history")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)
    diagnostics = _diagnostics(report)

    assert "secrets/private.md" not in rendered
    assert diagnostics["recovery.git.last_canonical_commit"].status == "unknown"
    assert "protected or policy-excluded" in diagnostics["recovery.git.last_canonical_commit"].summary
