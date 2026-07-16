from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    (vault / "wiki" / "note.md").write_text("---\nid: note\n---\n", encoding="utf-8")
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault}\nfeatures:\n  graphify: {'true' if enabled else 'false'}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return vault


def test_graph_build_and_status_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(tmp_path, monkeypatch, enabled=True)

    build_result = main(["graph", "build", "knowledge", "--json"])
    built = json.loads(capsys.readouterr().out)
    status_result = main(["graph", "status", "knowledge", "--json"])
    status = json.loads(capsys.readouterr().out)

    assert build_result == 0
    assert status_result == 0
    assert built["status"] == "clean"
    assert status["status"] == "clean"


def test_graph_command_requires_feature_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(tmp_path, monkeypatch, enabled=False)

    result = main(["graph", "status", "knowledge"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Graphify feature is disabled" in captured.err
