"""Deterministic flashcard workload planning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lifeos.diagnostics import (
    DiagnosticError,
    diagnostic_error_message,
    diagnostics_from_findings,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown

_MAX_EXACT_CANDIDATES = 24
_MAX_AVAILABLE_MINUTES = 1440


class StudyError(DiagnosticError):
    """Raised when flashcard metadata or review input is invalid."""


@dataclass(frozen=True, slots=True)
class Flashcard:
    card_id: str
    path: str
    topic: str
    question: str
    answer: str
    due: date
    estimated_seconds: int
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewSession:
    topic: str
    card_ids: tuple[str, ...]
    card_paths: tuple[str, ...]
    estimated_minutes: int
    overdue_cards: int


@dataclass(frozen=True, slots=True)
class RejectedReviewCandidate:
    card_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReviewOptimizationDiagnostics:
    solver: str
    objective_order: tuple[str, ...]
    selected_score: tuple[int, ...]
    unused_seconds: int
    binding_constraints: tuple[str, ...]
    rejected: tuple[RejectedReviewCandidate, ...]


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    as_of: date
    available_minutes: int
    selected_card_count: int
    deferred_due_card_count: int
    estimated_minutes: int
    sessions: tuple[ReviewSession, ...]
    diagnostics: ReviewOptimizationDiagnostics


def _required_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StudyError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _parse_date(value: object, *, key: str, path: Path) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise StudyError(f"{path}: {key} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise StudyError(f"{path}: {key} must be an ISO date") from exc


def load_flashcards(vault_root: Path) -> tuple[Flashcard, ...]:
    """Load active flashcards from the canonical vault."""
    cards: list[Flashcard] = []
    try:
        sources = iter_vault_markdown(vault_root, roots=("flashcards",))
    except VaultAccessError as exc:
        raise StudyError(str(exc)) from exc
    for source in sources:
        path = source.path
        parsed = parse_markdown_note(path, content=source.content)
        diagnostics = diagnostics_from_findings(parsed.findings, vault_root=vault_root)
        if diagnostics:
            raise StudyError(diagnostic_error_message(diagnostics[0]), diagnostic=diagnostics[0])
        data = dict(parsed.frontmatter)
        if data.get("type") != "flashcard" or data.get("status", "active") != "active":
            continue

        seconds = data.get("estimated_seconds", 30)
        if type(seconds) is not int or seconds <= 0 or seconds > 3600:
            raise StudyError(f"{path}: estimated_seconds must be an integer from 1 to 3600")

        raw_refs = data.get("source_refs", [])
        if not isinstance(raw_refs, list) or not all(
            isinstance(item, str) and item.strip() for item in raw_refs
        ):
            raise StudyError(f"{path}: source_refs must be a list of non-empty strings")
        source_refs = tuple(dict.fromkeys(item.strip() for item in raw_refs))

        cards.append(
            Flashcard(
                card_id=_required_str(data, "id", path),
                path=path.relative_to(vault_root).as_posix(),
                topic=_required_str(data, "topic", path),
                question=_required_str(data, "question", path),
                answer=_required_str(data, "answer", path),
                due=_parse_date(data.get("due"), key="due", path=path),
                estimated_seconds=seconds,
                source_refs=source_refs,
            )
        )

    seen: set[str] = set()
    for card in cards:
        if card.card_id in seen:
            raise StudyError(f"duplicate flashcard id: {card.card_id}")
        seen.add(card.card_id)
    return tuple(cards)


def _review_objective(
    selected: tuple[Flashcard, ...],
    *,
    as_of: date,
    used_seconds: int,
) -> tuple[int, ...]:
    overdue_days = tuple(max(0, (as_of - card.due).days) for card in selected)
    return (
        max(overdue_days, default=0),
        sum(overdue_days),
        used_seconds,
        len({card.topic.casefold() for card in selected}),
        len(selected),
    )


def _stable_selection_key(selected: tuple[Flashcard, ...]) -> tuple[str, ...]:
    return tuple(sorted(card.card_id for card in selected))


def _better_review_selection(
    candidate: tuple[Flashcard, ...],
    incumbent: tuple[Flashcard, ...],
    *,
    as_of: date,
) -> bool:
    candidate_used = sum(card.estimated_seconds for card in candidate)
    incumbent_used = sum(card.estimated_seconds for card in incumbent)
    candidate_score = _review_objective(candidate, as_of=as_of, used_seconds=candidate_used)
    incumbent_score = _review_objective(incumbent, as_of=as_of, used_seconds=incumbent_used)
    if candidate_score != incumbent_score:
        return candidate_score > incumbent_score
    return _stable_selection_key(candidate) < _stable_selection_key(incumbent)


def _exact_review_selection(
    cards: tuple[Flashcard, ...],
    *,
    as_of: date,
    budget_seconds: int,
) -> tuple[Flashcard, ...]:
    states: dict[int, tuple[Flashcard, ...]] = {0: ()}
    for card in cards:
        for used, selected in tuple(sorted(states.items(), reverse=True)):
            next_used = used + card.estimated_seconds
            if next_used > budget_seconds:
                continue
            candidate = (*selected, card)
            incumbent = states.get(next_used)
            if incumbent is None or _better_review_selection(candidate, incumbent, as_of=as_of):
                states[next_used] = candidate
    best: tuple[Flashcard, ...] = ()
    for selected in states.values():
        if _better_review_selection(selected, best, as_of=as_of):
            best = selected
    return tuple(sorted(best, key=lambda card: (card.due, card.topic.casefold(), card.card_id)))


def _fallback_review_selection(
    cards: tuple[Flashcard, ...],
    *,
    as_of: date,
    budget_seconds: int,
) -> tuple[Flashcard, ...]:
    ranked = sorted(
        cards,
        key=lambda card: (
            -max(0, (as_of - card.due).days),
            card.estimated_seconds,
            card.topic.casefold(),
            card.card_id,
        ),
    )
    selected: list[Flashcard] = []
    used = 0
    for card in ranked:
        if used + card.estimated_seconds <= budget_seconds:
            selected.append(card)
            used += card.estimated_seconds
    return tuple(sorted(selected, key=lambda card: (card.due, card.topic.casefold(), card.card_id)))


def build_review_plan(
    *,
    cards: tuple[Flashcard, ...],
    as_of: date,
    available_minutes: int,
    topic: str | None = None,
) -> ReviewPlan:
    if (
        type(available_minutes) is not int
        or available_minutes < 0
        or available_minutes > _MAX_AVAILABLE_MINUTES
    ):
        raise StudyError(f"available_minutes must be an integer from 0 to {_MAX_AVAILABLE_MINUTES}")
    if topic is not None and (not isinstance(topic, str) or not topic.strip()):
        raise StudyError("topic must be a non-empty string when provided")

    normalized_topic = topic.strip().casefold() if topic is not None else None
    due_cards = tuple(
        sorted(
            (
                card
                for card in cards
                if card.due <= as_of
                and (normalized_topic is None or card.topic.casefold() == normalized_topic)
            ),
            key=lambda card: (card.due, card.topic.casefold(), card.card_id),
        )
    )

    budget_seconds = available_minutes * 60
    if len(due_cards) <= _MAX_EXACT_CANDIDATES:
        solver = "exact-dynamic-programming"
        selected = _exact_review_selection(due_cards, as_of=as_of, budget_seconds=budget_seconds)
    else:
        solver = "deterministic-bounded-fallback"
        selected = _fallback_review_selection(due_cards, as_of=as_of, budget_seconds=budget_seconds)

    selected_ids = {card.card_id for card in selected}
    used_seconds = sum(card.estimated_seconds for card in selected)
    grouped: dict[str, list[Flashcard]] = {}
    for card in selected:
        grouped.setdefault(card.topic, []).append(card)

    sessions = tuple(
        ReviewSession(
            topic=topic_name,
            card_ids=tuple(card.card_id for card in topic_cards),
            card_paths=tuple(card.path for card in topic_cards),
            estimated_minutes=max(
                1,
                (sum(card.estimated_seconds for card in topic_cards) + 59) // 60,
            ),
            overdue_cards=sum(card.due < as_of for card in topic_cards),
        )
        for topic_name, topic_cards in sorted(grouped.items(), key=lambda item: item[0].casefold())
    )

    rejected = tuple(
        RejectedReviewCandidate(
            card_id=card.card_id,
            reason=(
                "exceeds the total time budget"
                if card.estimated_seconds > budget_seconds
                else "not selected by the ordered urgency, capacity, and variety objectives"
            ),
        )
        for card in due_cards
        if card.card_id not in selected_ids
    )
    constraints: list[str] = []
    if rejected:
        constraints.append("time budget")
    if solver == "deterministic-bounded-fallback":
        constraints.append(f"exact solver candidate limit ({_MAX_EXACT_CANDIDATES})")
    diagnostics = ReviewOptimizationDiagnostics(
        solver=solver,
        objective_order=(
            "maximum overdue age",
            "total overdue age",
            "capacity used",
            "topic variety",
            "card count",
            "stable card ids",
        ),
        selected_score=_review_objective(selected, as_of=as_of, used_seconds=used_seconds),
        unused_seconds=budget_seconds - used_seconds,
        binding_constraints=tuple(constraints),
        rejected=rejected,
    )

    return ReviewPlan(
        as_of=as_of,
        available_minutes=available_minutes,
        selected_card_count=len(selected),
        deferred_due_card_count=len(due_cards) - len(selected),
        estimated_minutes=(used_seconds + 59) // 60,
        sessions=sessions,
        diagnostics=diagnostics,
    )


def serialize_review_plan(plan: ReviewPlan) -> str:
    return json.dumps(asdict(plan), sort_keys=True, default=str, indent=2)


def format_review_plan(plan: ReviewPlan) -> str:
    lines = [
        f"Review plan for {plan.as_of.isoformat()}",
        f"Selected: {plan.selected_card_count} cards in {plan.estimated_minutes} minutes",
        f"Deferred due cards: {plan.deferred_due_card_count}",
        f"Optimizer: {plan.diagnostics.solver}; unused: {plan.diagnostics.unused_seconds} seconds",
        "",
    ]
    if not plan.sessions:
        lines.append("No due cards fit the current review budget.")
        return "\n".join(lines)
    for session in plan.sessions:
        lines.append(
            f"- {session.topic}: {len(session.card_ids)} cards, "
            f"{session.estimated_minutes} min, {session.overdue_cards} overdue"
        )
    return "\n".join(lines)
