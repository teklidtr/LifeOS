from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.entrypoint import main


def test_doctor_accepts_fresh_vault_from_outside_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ready"] is True
    assert payload["application"]["vault_root"] == str(vault.resolve())
    assert any(finding["code"] == "vault-bootstrap-valid" for finding in payload["findings"])
    assert captured.err == ""


def test_doctor_fails_closed_for_invalid_bootstrap_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    (vault / "wiki").rmdir()

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ready"] is False
    assert any(
        finding["code"] == "vault-bootstrap-invalid" and finding["state"] == "blocked"
        for finding in payload["findings"]
    )


def test_doctor_reports_missing_git_as_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "git" else real_which(name),
    )

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ready"] is False
    assert any(finding["code"] == "git-missing" for finding in payload["findings"])


def test_doctor_reports_unsupported_python_as_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    monkeypatch.setattr("lifeos.doctor.sys.version_info", (3, 10, 14))

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ready"] is False
    assert any(finding["code"] == "python-unsupported" for finding in payload["findings"])


def test_doctor_reports_missing_mcp_as_non_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()

    monkeypatch.setattr("lifeos.doctor.importlib.util.find_spec", lambda name: None)
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: None if name == "lifeos-mcp" else real_which(name),
    )

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ready"] is True
    finding_codes = {finding["code"] for finding in payload["findings"]}
    assert "mcp-sdk-missing" in finding_codes
    assert "mcp-executable-missing" in finding_codes
    assert payload["mcp_command"] is None


def test_doctor_reports_resolved_mcp_command_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    assert main(["init", str(vault)]) == 0
    capsys.readouterr()
    mcp_executable = str(tmp_path / "bin" / "lifeos-mcp")

    monkeypatch.setattr("lifeos.doctor.importlib.util.find_spec", lambda name: object())
    real_which = __import__("shutil").which
    monkeypatch.setattr(
        "lifeos.doctor.shutil.which",
        lambda name: mcp_executable if name == "lifeos-mcp" else real_which(name),
    )

    exit_code = main(["doctor", "--config", str(vault / "lifeos.yml"), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mcp_command"] == [
        mcp_executable,
        "--config",
        str((vault / "lifeos.yml").resolve()),
        "--actor-id",
        "<actor-id>",
    ]


def test_doctor_invalid_config_has_stable_json_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yml"

    exit_code = main(["doctor", "--config", str(missing), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"]["code"] == "config-error"
    assert payload["error"]["state"] == "blocked"


def test_global_help_mentions_doctor(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 0
    assert "doctor [OPTIONS]" in captured.out
