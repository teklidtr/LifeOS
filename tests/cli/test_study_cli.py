from __future__ import annotations

import json
from pathlib import Path

import pytest

from lifeos.cli import main


def test_study_review_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    cards = vault / "flashcards"
    cards.mkdir(parents=True)
    (cards / "card.md").write_text(
        "---\n"
        "type: flashcard\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-01\n"
        "estimated_seconds: 45\n"
        "---\n",
        encoding="utf-8",
    )
    (tmp_path / "lifeos.yml").write_text(
        f"vault_root: {vault}\nruntime_dir: .lifeos\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = main(["study", "review", "--date", "2026-07-15", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["selected_card_count"] == 1
    assert payload["sessions"][0]["topic"] == "Biology"


def test_study_review_rejects_bad_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(["study", "review", "--date", "bad-date"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Study error: invalid review date" in captured.err


def test_study_review_reports_flashcard_validation_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = tmp_path / "vault"
    cards = vault / "flashcards"
    cards.mkdir(parents=True)
    (cards / "card.md").write_text(
        "---\n"
        "type: flashcard\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-01\n"
        "estimated_seconds: 0\n"
        "---\n",
        encoding="utf-8",
    )
    (tmp_path / "lifeos.yml").write_text(f"vault_root: {vault}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(["study", "review"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Study error:" in captured.err
    assert "estimated_seconds" in captured.err
    assert "invalid review date" not in captured.err
