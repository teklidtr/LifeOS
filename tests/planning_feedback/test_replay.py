from __future__ import annotations

from dataclasses import replace
from datetime import date

from lifeos.feedback import FeedbackObservation, ReplayContext, replay_history
from lifeos.planning import PlanningAction


def observation(
    event_id: str,
    day: date,
    *,
    actual: int | None,
    outcome: str = "done",
    completion: float | None = 1.0,
) -> FeedbackObservation:
    return FeedbackObservation(
        1,
        f"obs-{event_id}",
        event_id,
        "plans/p.md",
        f"hash-{event_id}",
        int(event_id.removeprefix("e")),
        day,
        "plan-p",
        "goal-g",
        "task-a",
        "Write note",
        "writing",
        "writing",
        "medium",
        "medium",
        False,
        outcome,  # type: ignore[arg-type]
        completion,
        30,
        actual,
        "medium",
        "medium",
        "medium",
        None,
        None,
        None,
        (),
    )


def test_replay_is_deterministic_and_does_not_leak_same_day_outcome() -> None:
    action = PlanningAction(
        "task-a",
        "Write note",
        "todo",
        30,
        "medium",
        "medium",
        "writing",
        "goal-g",
        "plan-p",
        None,
        (),
        "plans/p.md",
    )
    history = tuple(
        observation(f"e{index}", date(2026, 7, 10 + index), actual=60)
        for index in range(1, 5)
    ) + (
        observation("e5", date(2026, 7, 16), actual=20),
    )
    context = ReplayContext(date(2026, 7, 16), 50, "medium", "medium")

    first = replay_history(
        actions=(action,), observations=history, contexts=(context,), mode="shadow"
    )
    second = replay_history(
        actions=(action,), observations=reversed(history), contexts=(context,), mode="shadow"
    )

    assert first == second
    day = first.days[0]
    assert day.changed_task_ids == ("task-a",)
    assert day.baseline.explicit_outcomes == 1
    assert day.baseline.actual_minutes == 20
    assert day.baseline.missing_outcomes == 0
    assert day.adaptive.selected_minutes > day.baseline.selected_minutes
    assert "noncausal" in first.caveat


def test_replay_keeps_missing_outcomes_separate_from_completion() -> None:
    action = PlanningAction(
        "task-a",
        "Write note",
        "todo",
        30,
        "medium",
        "medium",
        "writing",
        "goal-g",
        "plan-p",
        None,
        (),
        "plans/p.md",
    )
    result = replay_history(
        actions=(action,),
        observations=(),
        contexts=(ReplayContext(date(2026, 7, 16), 60),),
        mode="off",
    )

    metrics = result.days[0].baseline
    assert metrics.missing_outcomes == 1
    assert metrics.explicit_outcomes == 0
    assert metrics.completion_fraction is None
    assert metrics.mean_absolute_estimate_error is None


def test_replay_fingerprint_covers_actions_and_dismissed_evidence() -> None:
    action = PlanningAction(
        "task-a",
        "Write note",
        "todo",
        30,
        "medium",
        "medium",
        "writing",
        "goal-g",
        "plan-p",
        None,
        (),
        "plans/p.md",
    )
    context = ReplayContext(date(2026, 7, 16), 60)
    baseline = replay_history(
        actions=(action,), observations=(), contexts=(context,), mode="shadow"
    )
    changed_action = replay_history(
        actions=(replace(action, duration=45),),
        observations=(),
        contexts=(context,),
        mode="shadow",
    )
    dismissed = replay_history(
        actions=(action,),
        observations=(),
        contexts=(context,),
        mode="shadow",
        dismissed_diagnosis_fingerprints=("fingerprint-1",),
    )

    assert baseline.source_fingerprint != changed_action.source_fingerprint
    assert baseline.source_fingerprint != dismissed.source_fingerprint
