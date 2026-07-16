from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault}\nruntime_dir: .lifeos\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return vault


def test_context_build_json_outputs_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = _configure(tmp_path, monkeypatch)
    wiki = vault / "wiki"
    wiki.mkdir()
    (wiki / "sleep.md").write_text(
        "---\ntitle: Sleep\ndescription: Recovery basics.\n---\nSleep supports recovery.\n",
        encoding="utf-8",
    )

    result = main(["context", "build", "sleep recovery", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["sources"][0]["path"] == "wiki/sleep.md"


def test_context_build_rejects_invalid_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(tmp_path, monkeypatch)

    result = main(["context", "build", "sleep", "--limit", "0"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Context error: limit must be a positive integer" in captured.err
