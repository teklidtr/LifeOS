from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def _commit_all(
    repository: Path,
    message: str,
    *,
    env: dict[str, str] | None = None,
) -> str:
    _git(repository, "add", "-A", env=env)
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
        env=env,
    )
    return _git(repository, "rev-parse", "HEAD", env=env).stdout.strip()


def _doctor_json(vault: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)
    return exit_code, payload


def _diagnostics(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    recovery = payload["recovery"]
    assert isinstance(recovery, dict)
    raw = recovery["diagnostics"]
    assert isinstance(raw, list)
    return {str(item["id"]): item for item in raw if isinstance(item, dict)}


def test_doctor_distinguishes_git_repository_without_any_commit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    exit_code, payload = _doctor_json(vault, capsys)
    diagnostics = _diagnostics(payload)
    recovery = payload["recovery"]
    assert isinstance(recovery, dict)

    assert exit_code == 0
    assert payload["ready"] is True
    assert diagnostics["recovery.git.repository"]["status"] == "pass"
    assert diagnostics["recovery.git.last_canonical_commit"]["status"] == "failure"
    assert diagnostics["recovery.backup.external"]["status"] == "unknown"
    assert diagnostics["recovery.runtime.disposable"]["status"] == "info"
    assert recovery["committed_canonical_count"] == 0


def test_doctor_reports_vault_outside_git_as_recovery_risk(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    shutil.rmtree(vault / ".git")

    exit_code, payload = _doctor_json(vault, capsys)
    diagnostics = _diagnostics(payload)

    assert exit_code == 1
    assert diagnostics["recovery.git.repository"]["status"] == "failure"
    assert diagnostics["recovery.git.repository"]["severity"] == "error"
    assert diagnostics["recovery.git.last_canonical_commit"]["status"] == "unknown"


def test_doctor_reports_clean_committed_canonical_history_without_age_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "clean.md").write_text("canonical body\n", encoding="utf-8")
    _commit_all(vault, "initial canonical snapshot")

    exit_code, payload = _doctor_json(vault, capsys)
    diagnostics = _diagnostics(payload)
    recovery = payload["recovery"]
    assert isinstance(recovery, dict)
    last_commit = recovery["last_canonical_commit"]
    assert isinstance(last_commit, dict)

    assert exit_code == 0
    assert diagnostics["recovery.git.last_canonical_commit"]["status"] == "info"
    assert diagnostics["recovery.git.uncommitted_canonical"]["status"] == "pass"
    assert diagnostics["recovery.git.untracked_canonical"]["status"] == "pass"
    assert diagnostics["recovery.git.ignored_canonical"]["status"] == "pass"
    assert isinstance(last_commit["age_days"], int)
    assert last_commit["age_days"] >= 0


def test_doctor_reports_dirty_staged_deleted_untracked_and_ignored_canonical_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    modified = vault / "wiki" / "modified.md"
    deleted = vault / "plans" / "deleted.md"
    modified.write_text("before\n", encoding="utf-8")
    deleted.write_text("before\n", encoding="utf-8")
    _commit_all(vault, "baseline")

    modified.write_text("after\n", encoding="utf-8")
    staged = vault / "goals" / "staged.md"
    staged.write_text("staged\n", encoding="utf-8")
    _git(vault, "add", "goals/staged.md")
    deleted.unlink()
    untracked = vault / "raw" / "new.md"
    untracked.write_text("new\n", encoding="utf-8")
    with (vault / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("wiki/ignored.md\n")
    ignored = vault / "wiki" / "ignored.md"
    ignored.write_text("ignored\n", encoding="utf-8")
    runtime_file = vault / ".lifeos" / "cache.bin"
    runtime_file.parent.mkdir()
    runtime_file.write_bytes(b"derived")

    exit_code, payload = _doctor_json(vault, capsys)
    diagnostics = _diagnostics(payload)
    recovery = payload["recovery"]
    assert isinstance(recovery, dict)

    assert exit_code == 0
    assert diagnostics["recovery.git.uncommitted_canonical"]["status"] == "warning"
    assert diagnostics["recovery.git.untracked_canonical"]["status"] == "warning"
    assert diagnostics["recovery.git.ignored_canonical"]["status"] == "warning"
    assert set(recovery["uncommitted_paths"]) == {
        ".gitignore",
        "goals/staged.md",
        "plans/deleted.md",
        "wiki/modified.md",
    }
    assert recovery["staged_paths"] == ["goals/staged.md"]
    assert "plans/deleted.md" in recovery["deleted_paths"]
    assert recovery["untracked_paths"] == ["raw/new.md"]
    assert recovery["ignored_paths"] == ["wiki/ignored.md"]
    serialized = json.dumps(payload)
    assert ".lifeos/cache.bin" not in serialized
    assert "commit disposable runtime" not in serialized.lower()


def test_recovery_latest_commit_is_scoped_to_nested_vault_not_parent_repository(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    vault = repository / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    shutil.rmtree(vault / ".git")
    _git(repository, "init", "-q")
    (vault / "wiki" / "nested.md").write_text("nested\n", encoding="utf-8")
    vault_commit = _commit_all(repository, "commit vault")
    (repository / "outside.txt").write_text("unrelated\n", encoding="utf-8")
    outside_commit = _commit_all(repository, "commit unrelated parent file")
    assert outside_commit != vault_commit

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))

    assert report.last_canonical_commit is not None
    assert report.last_canonical_commit.sha == vault_commit
    assert report.uncommitted_paths == ()
    assert report.untracked_paths == ()


def test_old_canonical_commit_age_is_information_not_recovery_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki" / "old.md").write_text("old but clean\n", encoding="utf-8")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2020-01-02T03:04:05+00:00"
    env["GIT_COMMITTER_DATE"] = "2020-01-02T03:04:05+00:00"
    _commit_all(vault, "old snapshot", env=env)

    report = collect_recovery_readiness(load_config(vault / "lifeos.yml"))
    diagnostics = {item.id: item for item in report.diagnostics}

    assert report.last_canonical_commit is not None
    assert report.last_canonical_commit.age_days > 1_000
    assert diagnostics["recovery.git.last_canonical_commit"].status == "info"
    assert diagnostics["recovery.git.uncommitted_canonical"].status == "pass"
    assert diagnostics["recovery.git.untracked_canonical"].status == "pass"
    assert diagnostics["recovery.git.ignored_canonical"].status == "pass"


def test_doctor_recovery_is_read_only_and_does_not_emit_note_contents(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    secret = "SECRET-CANONICAL-BODY-DO-NOT-EMIT"
    note = vault / "wiki" / "private.md"
    note.write_text(f"{secret}\n", encoding="utf-8")
    _commit_all(vault, "canonical snapshot")
    runtime = vault / ".lifeos" / "marker.bin"
    runtime.parent.mkdir()
    runtime.write_bytes(b"runtime-marker")

    index_before = (vault / ".git" / "index").read_bytes()
    head_before = _git(vault, "rev-parse", "HEAD").stdout.strip()
    note_before = note.read_bytes()
    runtime_before = runtime.read_bytes()

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert secret not in captured.out
    assert note.read_bytes() == note_before
    assert runtime.read_bytes() == runtime_before
    assert (vault / ".git" / "index").read_bytes() == index_before
    assert _git(vault, "rev-parse", "HEAD").stdout.strip() == head_before


def test_human_doctor_includes_recovery_diagnostic_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    assert main(["doctor", "--config", str(vault / "lifeos.yml")]) == 0

    output = capsys.readouterr().out
    assert "Recovery readiness" in output
    assert "recovery.git.repository" in output
    assert "recovery.backup.external" in output
    assert "unknown" in output
