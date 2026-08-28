from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness


def test_recovery_git_queries_disable_optional_locks_and_force_literal_pathspecs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["command"] = command
        observed["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(recovery_readiness.subprocess, "run", fake_run)

    result = recovery_readiness._run_git(
        "git",
        cwd=tmp_path,
        arguments=("rev-parse", "--show-toplevel"),
        check=False,
    )

    assert result.returncode == 0
    env = observed["env"]
    assert isinstance(env, dict)
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_LITERAL_PATHSPECS"] == "1"
    assert observed["command"] == ["git", "rev-parse", "--show-toplevel"]
