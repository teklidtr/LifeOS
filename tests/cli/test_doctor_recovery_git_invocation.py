from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import lifeos.recovery_readiness as recovery_readiness


def test_recovery_git_queries_disable_side_effecting_git_features(
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
    assert "GIT_LITERAL_PATHSPECS" not in env
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_PAGER"] == ""
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "core.fsmonitor"
    assert env["GIT_CONFIG_VALUE_0"] == "false"
    assert observed["command"] == ["git", "rev-parse", "--show-toplevel"]


def test_recovery_git_queries_do_not_execute_configured_fsmonitor(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repository)], check=True, capture_output=True)

    marker = tmp_path / "fsmonitor-called"
    fsmonitor = tmp_path / "fsmonitor.sh"
    fsmonitor.write_text(
        "#!/bin/sh\n"
        f"touch {marker!s}\n"
        "printf '{}\\n'\n",
        encoding="utf-8",
    )
    fsmonitor.chmod(0o755)
    subprocess.run(
        ["git", "-C", str(repository), "config", "core.fsmonitor", str(fsmonitor)],
        check=True,
        capture_output=True,
    )

    result = recovery_readiness._run_git(
        "git",
        cwd=repository,
        arguments=("ls-files", "--others", "--exclude-standard", "-z", "--", "."),
    )

    assert result.returncode == 0
    assert not marker.exists()
