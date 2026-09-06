from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from lifeos.feedback import FeedbackObservation, calibrate_duration


AS_OF = date(2026, 7, 16)


def observation(
    index: int,
    *,
    task: str = "task",
    plan: str = "plan",
    mode: str = "writing",
    shape: str = "synthesis",
    planned: int = 30,
    actual: int = 45,
    outcome: str = "done",
    fraction: float | None = 1.0,
    age: int = 0,
) -> FeedbackObservation:
    return FeedbackObservation(
        schema_version=1,
        observation_id=f"o{index}",
        event_id=f"e{index}",
        source_path="plans/p.md",
        source_hash="h",
        source_index=index,
        day=AS_OF - timedelta(days=age),
        plan_id=plan,
        goal_id="goal",
        task_id=task,
        task_title="Task",
        task_shape=shape,
        mode=mode,
        task_energy="medium",
        task_motivation="medium",
        blocked=False,
        outcome=outcome,  # type: ignore[arg-type]
        completion_fraction=fraction,
        planned_minutes=planned,
        actual_minutes=actual,
        energy_before="medium",
        energy_after=None,
        motivation_before="medium",
        started_at=None,
        ended_at=None,
        reason=None,
        correction_lineage=(),
    )


def test_no_evidence_one_sample_and_threshold_boundary() -> None:
    assert (
        calibrate_duration(
            observations=(), task_id="task", declared_minutes=30, as_of=AS_OF
        ).calibrated_minutes
        == 30
    )
    one = calibrate_duration(
        observations=(observation(1),), task_id="task", declared_minutes=30, as_of=AS_OF
    )
    assert one.confidence == "insufficient"
    enough = calibrate_duration(
        observations=tuple(observation(i) for i in range(3)),
        task_id="task",
        declared_minutes=30,
        as_of=AS_OF,
    )
    assert enough.evidence_level == "task"
    assert enough.calibrated_minutes > 30


def test_under_and_overestimation_are_cautious_and_bounded() -> None:
    under = calibrate_duration(
        observations=tuple(observation(i, actual=60) for i in range(8)),
        task_id="task",
        declared_minutes=30,
        as_of=AS_OF,
    )
    over = calibrate_duration(
        observations=tuple(observation(i, actual=12) for i in range(8)),
        task_id="task",
        declared_minutes=30,
        as_of=AS_OF,
    )
    assert under.calibrated_minutes == 60
    assert under.direction == "underestimated"
    assert over.calibrated_minutes == 15
    assert over.direction == "overestimated"


def test_hierarchical_fallback_ordering() -> None:
    samples = [
        observation(i, task="other", plan="plan", mode="writing", shape="synthesis")
        for i in range(8)
    ]
    shape = calibrate_duration(
        observations=samples,
        task_id="task",
        task_shape="synthesis",
        plan_id="plan",
        mode="writing",
        declared_minutes=30,
        as_of=AS_OF,
    )
    assert shape.evidence_level == "task_shape"
    samples = [replace(item, task_shape="other") for item in samples]
    plan = calibrate_duration(
        observations=samples,
        task_id="task",
        task_shape="synthesis",
        plan_id="plan",
        mode="writing",
        declared_minutes=30,
        as_of=AS_OF,
    )
    assert plan.evidence_level == "plan"


def test_partial_completion_normalizes_duration() -> None:
    samples = tuple(
        observation(i, outcome="partial", actual=20, fraction=0.5, planned=30) for i in range(4)
    )
    forecast = calibrate_duration(
        observations=samples, task_id="task", declared_minutes=30, as_of=AS_OF
    )
    assert forecast.calibrated_minutes > 30


def test_outliers_stale_disabled_and_shuffle_determinism() -> None:
    samples = [observation(i, actual=30 + (i % 2)) for i in range(6)]
    samples.append(observation(99, actual=300))
    first = calibrate_duration(
        observations=samples, task_id="task", declared_minutes=30, as_of=AS_OF
    )
    second = calibrate_duration(
        observations=reversed(samples), task_id="task", declared_minutes=30, as_of=AS_OF
    )
    assert first == second
    assert first.excluded_outliers == 1
    stale = calibrate_duration(
        observations=tuple(observation(i, age=400) for i in range(6)),
        task_id="task",
        declared_minutes=30,
        as_of=AS_OF,
    )
    assert stale.confidence == "insufficient"
    disabled = calibrate_duration(
        observations=samples, task_id="task", declared_minutes=30, as_of=AS_OF, enabled=False
    )
    assert disabled.calibrated_minutes == 30
    assert disabled.enabled is False
