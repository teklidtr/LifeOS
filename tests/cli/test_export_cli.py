from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> Path:
    vault = tmp_path / "vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "note.md").write_text("Note.\n", encoding="utf-8")
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault}\nfeatures:\n  exports: {'true' if enabled else 'false'}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return vault


def test_export_build_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = _configure(tmp_path, monkeypatch, enabled=True)

    result = main(["export", "build", "public-wiki", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["kind"] == "public-wiki"
    assert (vault / ".lifeos" / payload["output_dir"] / "manifest.json").exists()


def test_export_build_requires_feature_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(tmp_path, monkeypatch, enabled=False)

    result = main(["export", "build", "public-wiki"])

    captured = capsys.readouterr()
    assert result == 1
    assert "exports feature is disabled" in captured.err


def test_export_status_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(tmp_path, monkeypatch, enabled=True)
    assert main(["export", "build", "public-wiki", "--json"]) == 0
    capsys.readouterr()

    result = main(["export", "status", "public-wiki", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    payload = json.loads(captured.out)
    assert payload["status"] == "ready"
    assert payload["active_generation"]
    assert payload["recovery_state"] == "none"
