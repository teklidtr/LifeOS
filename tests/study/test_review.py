from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.study import Flashcard, StudyError, build_review_plan, load_flashcards


def _write_card(
    vault: Path,
    name: str,
    *,
    card_id: str,
    topic: str,
    due: str,
    seconds: int = 30,
    status: str = "active",
) -> None:
    root = vault / "flashcards"
    root.mkdir(exist_ok=True)
    (root / f"{name}.md").write_text(
        "---\n"
        "type: flashcard\n"
        f"id: {card_id}\n"
        f"topic: {topic}\n"
        f"question: Question {card_id}?\n"
        f"answer: Answer {card_id}.\n"
        f"due: {due}\n"
        f"estimated_seconds: {seconds}\n"
        f"status: {status}\n"
        "source_refs:\n"
        "  - wiki/source.md\n"
        "---\n",
        encoding="utf-8",
    )


def test_load_flashcards_reads_active_cards(tmp_path: Path) -> None:
    _write_card(tmp_path, "a", card_id="card-a", topic="Biology", due="2026-07-01")
    _write_card(
        tmp_path,
        "archived",
        card_id="card-z",
        topic="Biology",
        due="2026-07-01",
        status="archived",
    )

    cards = load_flashcards(tmp_path)

    assert len(cards) == 1
    assert cards[0].card_id == "card-a"
    assert cards[0].source_refs == ("wiki/source.md",)


def test_review_plan_prioritizes_overdue_and_groups_by_topic() -> None:
    cards = (
        Flashcard("new", "flashcards/new.md", "Physics", "Q", "A", date(2026, 7, 15), 60, ()),
        Flashcard("old-a", "flashcards/a.md", "Biology", "Q", "A", date(2026, 7, 1), 60, ()),
        Flashcard("old-b", "flashcards/b.md", "Biology", "Q", "A", date(2026, 7, 2), 60, ()),
        Flashcard("future", "flashcards/f.md", "Biology", "Q", "A", date(2026, 8, 1), 60, ()),
    )

    plan = build_review_plan(cards=cards, as_of=date(2026, 7, 15), available_minutes=2)

    assert plan.selected_card_count == 2
    assert plan.deferred_due_card_count == 1
    assert len(plan.sessions) == 1
    assert plan.sessions[0].topic == "Biology"
    assert plan.sessions[0].card_ids == ("old-a", "old-b")
    assert plan.sessions[0].overdue_cards == 2


def test_review_plan_respects_topic_filter_and_budget() -> None:
    cards = (
        Flashcard("bio", "flashcards/bio.md", "Biology", "Q", "A", date(2026, 7, 1), 90, ()),
        Flashcard("chem", "flashcards/chem.md", "Chemistry", "Q", "A", date(2026, 7, 1), 30, ()),
    )

    plan = build_review_plan(
        cards=cards,
        as_of=date(2026, 7, 15),
        available_minutes=1,
        topic="chemistry",
    )

    assert plan.selected_card_count == 1
    assert plan.sessions[0].card_ids == ("chem",)


def test_duplicate_card_ids_are_rejected(tmp_path: Path) -> None:
    _write_card(tmp_path, "a", card_id="same", topic="Biology", due="2026-07-01")
    _write_card(tmp_path, "b", card_id="same", topic="Physics", due="2026-07-01")

    with pytest.raises(StudyError, match="duplicate"):
        load_flashcards(tmp_path)


def test_flashcard_source_refs_are_normalized_and_deduplicated(tmp_path: Path) -> None:
    cards = tmp_path / "flashcards"
    cards.mkdir()
    (cards / "card.md").write_text(
        "---\n"
        "type: flashcard\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-01\n"
        "source_refs:\n"
        "  - ' wiki/atp '\n"
        "  - wiki/atp\n"
        "---\n",
        encoding="utf-8",
    )

    loaded = load_flashcards(tmp_path)

    assert loaded[0].source_refs == ("wiki/atp",)


def test_flashcard_source_refs_reject_blank_entries(tmp_path: Path) -> None:
    cards = tmp_path / "flashcards"
    cards.mkdir()
    (cards / "card.md").write_text(
        "---\n"
        "type: flashcard\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-01\n"
        "source_refs:\n"
        "  - '   '\n"
        "---\n",
        encoding="utf-8",
    )

    with pytest.raises(StudyError, match="source_refs"):
        load_flashcards(tmp_path)


def test_review_topic_filter_ignores_surrounding_whitespace() -> None:
    cards = (
        Flashcard(
            "card-1",
            "flashcards/card-1.md",
            "Biology",
            "Question",
            "Answer",
            date(2026, 7, 1),
            30,
            (),
        ),
    )

    plan = build_review_plan(
        cards=cards,
        as_of=date(2026, 7, 15),
        available_minutes=5,
        topic=" Biology ",
    )

    assert plan.selected_card_count == 1


def test_flashcard_due_rejects_datetime_metadata(tmp_path: Path) -> None:
    cards = tmp_path / "flashcards"
    cards.mkdir()
    (cards / "card.md").write_text(
        "---\n"
        "type: flashcard\n"
        "id: card-1\n"
        "topic: Biology\n"
        "question: What is ATP?\n"
        "answer: Cellular energy currency.\n"
        "due: 2026-07-01T12:00:00\n"
        "---\n",
        encoding="utf-8",
    )

    with pytest.raises(StudyError, match="due must be an ISO date"):
        load_flashcards(tmp_path)


def test_review_optimizer_fills_capacity_for_equal_urgency_counterexample() -> None:
    cards = (
        Flashcard("a-long", "flashcards/a.md", "Biology", "Q", "A", date(2026, 7, 1), 100, ()),
        Flashcard("b-short", "flashcards/b.md", "Biology", "Q", "A", date(2026, 7, 1), 60, ()),
        Flashcard("c-short", "flashcards/c.md", "Physics", "Q", "A", date(2026, 7, 1), 60, ()),
    )

    plan = build_review_plan(cards=cards, as_of=date(2026, 7, 15), available_minutes=2)

    selected = {card_id for session in plan.sessions for card_id in session.card_ids}
    assert selected == {"b-short", "c-short"}
    assert plan.diagnostics.solver == "exact-dynamic-programming"
    assert plan.diagnostics.unused_seconds == 0


def test_review_optimizer_keeps_most_overdue_card_as_primary_objective() -> None:
    cards = (
        Flashcard("critical", "flashcards/a.md", "Biology", "Q", "A", date(2026, 6, 1), 50, ()),
        Flashcard("today-a", "flashcards/b.md", "Biology", "Q", "A", date(2026, 7, 15), 30, ()),
        Flashcard("today-b", "flashcards/c.md", "Physics", "Q", "A", date(2026, 7, 15), 30, ()),
    )

    plan = build_review_plan(cards=cards, as_of=date(2026, 7, 15), available_minutes=1)

    selected = {card_id for session in plan.sessions for card_id in session.card_ids}
    assert "critical" in selected
    assert plan.diagnostics.objective_order[0] == "maximum overdue age"


def test_review_optimizer_is_stable_under_shuffled_input() -> None:
    cards = tuple(
        Flashcard(
            f"card-{index}",
            f"flashcards/{index}.md",
            "Biology" if index % 2 else "Physics",
            "Q",
            "A",
            date(2026, 7, 1),
            35,
            (),
        )
        for index in range(5)
    )

    first = build_review_plan(cards=cards, as_of=date(2026, 7, 15), available_minutes=2)
    second = build_review_plan(
        cards=tuple(reversed(cards)), as_of=date(2026, 7, 15), available_minutes=2
    )

    assert first == second


def test_review_optimizer_supports_zero_and_maximum_capacity() -> None:
    card = Flashcard("card", "flashcards/card.md", "Biology", "Q", "A", date(2026, 7, 1), 30, ())

    empty = build_review_plan(cards=(card,), as_of=date(2026, 7, 15), available_minutes=0)
    maximum = build_review_plan(cards=(card,), as_of=date(2026, 7, 15), available_minutes=1440)

    assert empty.selected_card_count == 0
    assert empty.diagnostics.unused_seconds == 0
    assert maximum.selected_card_count == 1
    with pytest.raises(StudyError, match="0 to 1440"):
        build_review_plan(cards=(card,), as_of=date(2026, 7, 15), available_minutes=1441)


def test_review_optimizer_uses_deterministic_fallback_above_bound() -> None:
    cards = tuple(
        Flashcard(
            f"card-{index:02d}",
            f"flashcards/{index:02d}.md",
            f"Topic {index % 3}",
            "Q",
            "A",
            date(2026, 7, 1),
            30,
            (),
        )
        for index in range(25)
    )

    plan = build_review_plan(cards=cards, as_of=date(2026, 7, 15), available_minutes=5)

    assert plan.diagnostics.solver == "deterministic-bounded-fallback"
    assert "exact solver candidate limit (24)" in plan.diagnostics.binding_constraints
    assert plan.selected_card_count == 10
