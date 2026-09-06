from __future__ import annotations

from datetime import date, timedelta

from lifeos.feedback import FeedbackObservation, diagnose_repeated_avoidance

AS_OF = date(2026, 7, 16)


def event(
    index: int,
    *,
    outcome: str = "skipped",
    reason: str | None = None,
    energy: str | None = None,
    motivation: str | None = None,
    task: str = "task",
    actual: int | None = None,
    planned: int = 30,
) -> FeedbackObservation:
    return FeedbackObservation(
        1,
        f"o{index}",
        f"e{index}",
        "plans/p.md",
        "h",
        index,
        AS_OF - timedelta(days=index),
        "plan",
        "goal",
        task,
        "Task",
        "shape",
        "writing",
        "medium",
        "medium",
        False,
        outcome,
        0.5 if outcome == "partial" else 0.0,
        planned,
        actual,
        energy,
        None,
        motivation,
        None,
        None,
        reason,
        (),
        False,
    )  # type: ignore[arg-type]


def test_one_skip_is_not_a_pattern_and_boundary_is_explicit() -> None:
    assert diagnose_repeated_avoidance(observations=(event(1),), as_of=AS_OF) == ()
    result = diagnose_repeated_avoidance(
        observations=tuple(event(i) for i in range(3)), as_of=AS_OF
    )
    assert len(result) == 1
    assert result[0].confidence == "low"


def test_diagnoses_underspecified_blocked_oversized_and_estimate_error() -> None:
    unclear = diagnose_repeated_avoidance(
        observations=tuple(event(i, reason="unclear next step") for i in range(3)), as_of=AS_OF
    )[0]
    assert unclear.kind == "underspecified"
    blocked = diagnose_repeated_avoidance(
        observations=tuple(event(i, reason="blocked waiting") for i in range(3)), as_of=AS_OF
    )[0]
    assert blocked.kind == "blocked"
    oversized = diagnose_repeated_avoidance(
        observations=tuple(event(i, reason="too big for today") for i in range(3)), as_of=AS_OF
    )[0]
    assert oversized.kind == "oversized"
    estimates = tuple(event(i, outcome="partial", actual=60) for i in range(3))
    assert (
        diagnose_repeated_avoidance(observations=estimates, as_of=AS_OF)[0].kind == "estimate_error"
    )


def test_energy_and_motivation_hypotheses_are_separate() -> None:
    motivation = diagnose_repeated_avoidance(
        observations=tuple(event(i, energy="high", motivation="low") for i in range(3)), as_of=AS_OF
    )[0]
    energy = diagnose_repeated_avoidance(
        observations=tuple(event(i, energy="low", motivation="high") for i in range(3)), as_of=AS_OF
    )[0]
    assert motivation.kind == "motivation_mismatch"
    assert energy.kind == "capacity_mismatch"


def test_mixed_success_suppresses_and_dismissal_is_fingerprint_bound() -> None:
    mixed = tuple(event(i) for i in range(3)) + tuple(
        event(10 + i, outcome="done", actual=30) for i in range(3)
    )
    assert diagnose_repeated_avoidance(observations=mixed, as_of=AS_OF) == ()
    adverse = tuple(event(i) for i in range(3))
    original = diagnose_repeated_avoidance(observations=adverse, as_of=AS_OF)[0]
    dismissed = diagnose_repeated_avoidance(
        observations=adverse, as_of=AS_OF, dismissed_fingerprints=(original.evidence_fingerprint,)
    )[0]
    assert dismissed.dismissed is True
    changed = diagnose_repeated_avoidance(
        observations=adverse + (event(4),),
        as_of=AS_OF,
        dismissed_fingerprints=(original.evidence_fingerprint,),
    )[0]
    assert changed.dismissed is False


def test_ids_are_stable_and_language_is_not_punitive_or_clinical() -> None:
    observations = tuple(event(i, outcome="unaccounted") for i in range(4))
    first = diagnose_repeated_avoidance(observations=observations, as_of=AS_OF)[0]
    second = diagnose_repeated_avoidance(observations=reversed(observations), as_of=AS_OF)[0]
    assert first == second
    text = first.title + " " + first.hypothesis
    assert "discipline" in text
    assert "diagnosis" not in text.casefold()
    assert first.kind == "unaccounted"
