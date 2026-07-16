from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def test_observe_patterns_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    journal = vault / "journal"
    journal.mkdir(parents=True)
    for day in range(1, 6):
        (journal / f"2026-07-0{day}.md").write_text(
            f"---\ndate: 2026-07-0{day}\nmetrics:\n  sleep: {day}\n  energy: {day}\n---\n",
            encoding="utf-8",
        )
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "observe",
            "patterns",
            "--outcome",
            "energy",
            "--factor",
            "sleep",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["candidates"][0]["status"] == "candidate"
