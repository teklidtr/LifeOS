from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from lifeos.attention import evaluate_attention
from lifeos.daily import DailyInteractionError, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.study import StudySessionService


def write_card(vault: Path, name: str, due: str = "2026-07-15") -> Path:
    path = vault / "flashcards" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
id: {name}
type: flashcard
card_id: {name}
topic: Biology
question: Q
answer: A
due: {due}
estimated_seconds: 30
source_refs: []
---
""")
    return path


def body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


def test_session_lifecycle_and_canonical_result(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write_card(vault, "c1")
    service = StudySessionService(vault_root=vault, runtime_dir=runtime)
    now = datetime(2026, 7, 16, 10, tzinfo=timezone.utc)
    session = service.start(day=date(2026, 7, 16), minutes=5, session_id="s1", now=now)
    assert service.start(day=date(2026, 7, 16), minutes=5, session_id="s1", now=now) == session
    assert (
        service.transition(session_id="s1", action="pause", now=now + timedelta(minutes=1)).state
        == "paused"
    )
    assert (
        service.transition(session_id="s1", action="resume", now=now + timedelta(minutes=2)).state
        == "active"
    )
    finished = service.transition(session_id="s1", action="finish", now=now + timedelta(minutes=4))
    assert finished.actual_minutes == 4
    journal = vault / "journal" / "2026-07-16.md"
    assert "session_id: s1" in journal.read_text()
    assert body_bytes(journal) == b""
    assert service.list_open() == ()


def test_existing_journal_body_is_preserved_exactly(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write_card(vault, "c1")
    journal = vault / "journal" / "2026-07-16.md"
    journal.parent.mkdir()
    original_body = b"\r\n\r\nHuman study note with hard break.  \r\n\tTail"
    journal.write_bytes(
        b"---\ntype: journal\ntitle: '2026-07-16'\ndate: 2026-07-16\nstatus: active\nstudy_sessions: []\n---\n"
        + original_body
    )
    service = StudySessionService(vault_root=vault, runtime_dir=runtime)
    now = datetime(2026, 7, 16, 10, tzinfo=timezone.utc)
    service.start(day=date(2026, 7, 16), minutes=5, session_id="s1", now=now)

    service.transition(
        session_id="s1",
        action="finish",
        now=now + timedelta(minutes=4),
        expected_journal_hash=content_hash(journal.read_bytes()),
    )

    assert body_bytes(journal) == original_body
    assert b"session_id: s1" in journal.read_bytes()


def test_interrupted_session_appears_in_attention_and_source_changes_are_reported(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    card = write_card(vault, "c1")
    service = StudySessionService(vault_root=vault, runtime_dir=runtime)
    service.start(
        day=date(2026, 7, 16),
        minutes=5,
        session_id="s1",
        now=datetime(2026, 7, 16, 10, tzinfo=timezone.utc),
    )
    result = evaluate_attention(
        vault_root=vault, runtime_dir=runtime, as_of=datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
    )
    assert any(item.kind == "unfinished_study_session" for item in result.items)
    card.unlink()
    finished = service.transition(
        session_id="s1", action="abandon", now=datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
    )
    assert finished.source_changes == ("flashcards/c1.md",)


def test_invalid_transition_is_rejected(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write_card(vault, "c1")
    service = StudySessionService(vault_root=vault, runtime_dir=runtime)
    service.start(day=date(2026, 7, 16), minutes=5, session_id="s1")
    service.transition(session_id="s1", action="abandon")
    with pytest.raises(DailyInteractionError):
        service.transition(session_id="s1", action="resume")
