from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

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


def test_config_snapshot_recognizes_bom_prefixed_include(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.write_bytes(
        b"\xef\xbb\xbf[include]\n"
        b"\tpath = ../unsafe.conf\n"
        b"[core]\n"
        b"\tfilemode = true\n"
    )

    _raw, includes, filemode, ignorecase = recovery_readiness._config_snapshot(config)

    assert includes is True
    assert filemode is True
    assert ignorecase is False


def test_sandboxed_git_uses_pinned_object_store_after_path_swap(
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
    assert sandbox.object_fd is not None
    assert sandbox.object_fd_path is not None
    live_objects = vault / ".git" / "objects"
    original_objects = vault / ".git" / "objects-original"
    redirected = tmp_path / "protected-object-target"
    redirected.mkdir()

    sandbox_token = recovery_readiness._ACTIVE_SANDBOX.set(sandbox)
    try:
        live_objects.rename(original_objects)
        live_objects.symlink_to(redirected, target_is_directory=True)

        git = recovery_readiness._resolve_git_executable()
        assert git is not None
        result = recovery_readiness._run_git(
            git,
            cwd=vault,
            arguments=("cat-file", "-t", "HEAD"),
        )

        assert result.stdout.strip() == b"commit"
        assert sandbox.object_fd_path != str(live_objects)
    finally:
        if live_objects.is_symlink():
            live_objects.unlink()
        if original_objects.exists():
            original_objects.rename(live_objects)
        recovery_readiness._ACTIVE_SANDBOX.reset(sandbox_token)
        sandbox.close()


def test_sandbox_tempdir_failure_returns_unknown_not_exception(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    def fail_temporary_directory(*_args: object, **_kwargs: object) -> object:
        raise OSError("temporary filesystem unavailable")

    monkeypatch.setattr(
        recovery_readiness.tempfile,
        "TemporaryDirectory",
        fail_temporary_directory,
    )

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    repository = _diagnostics(report)["recovery.git.repository"]

    assert repository.status == "unknown"
    assert "metadata sandbox" in repository.summary
    assert "temporary filesystem unavailable" not in repository.summary


def test_hidden_scope_still_classifies_allowed_visible_ignored_path(
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
    with (vault / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("wiki/ignored.md\n")
    (vault / "wiki" / "baseline.md").write_text("baseline\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    protected = vault / "secrets" / "private.md"
    protected.parent.mkdir()
    protected.write_text("private\n", encoding="utf-8")
    ignored = vault / "wiki" / "ignored.md"
    ignored.write_text("visible ignored\n", encoding="utf-8")

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)
    diagnostics = _diagnostics(report)

    assert "wiki/ignored.md" in report.ignored_paths
    assert "wiki/ignored.md" not in report.untracked_paths
    assert "secrets/private.md" not in rendered
    assert diagnostics["recovery.git.ignored_canonical"].status == "unknown"
    assert diagnostics["recovery.git.untracked_canonical"].status == "unknown"


def test_protected_ignore_source_is_not_read_to_classify_visible_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "protected_prefixes:\n"
        "  - .gitignore\n"
        "  - secrets\n",
        encoding="utf-8",
    )
    (vault / ".gitignore").write_text("wiki/ignored.md\n", encoding="utf-8")
    (vault / "wiki" / "baseline.md").write_text("baseline\n", encoding="utf-8")
    _git(vault, "add", "system/retrieval-policy.yml", "wiki/baseline.md")
    _git(
        vault,
        "-c",
        "user.name=LifeOS Test",
        "-c",
        "user.email=lifeos@example.invalid",
        "commit",
        "-q",
        "-m",
        "baseline",
    )
    (vault / "secrets").mkdir()
    (vault / "secrets" / "private.md").write_text("private\n", encoding="utf-8")
    (vault / "wiki" / "ignored.md").write_text("candidate\n", encoding="utf-8")

    real_run_git = recovery_readiness._run_git
    check_ignore_queries: list[tuple[str, ...]] = []

    def recording_run_git(
        git_executable: str,
        *,
        cwd: Path,
        arguments: Any,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        normalized = tuple(arguments)
        if "check-ignore" in normalized:
            check_ignore_queries.append(normalized)
        return real_run_git(
            git_executable,
            cwd=cwd,
            arguments=arguments,
            check=check,
            input_bytes=input_bytes,
        )

    monkeypatch.setattr(recovery_readiness, "_run_git", recording_run_git)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    rendered = json.dumps(recovery_report_to_dict(report), ensure_ascii=True)

    assert check_ignore_queries == []
    assert "wiki/ignored.md" not in report.ignored_paths
    assert "wiki/ignored.md" not in report.untracked_paths
    assert ".gitignore" not in rendered
    assert "secrets/private.md" not in rendered
