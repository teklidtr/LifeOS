from __future__ import annotations

from datetime import date, timedelta

from lifeos.feedback import FeedbackObservation, summarize_capacity_fit

AS_OF = date(2026, 7, 16)


def observation(index: int, *, outcome: str = "done", energy: str | None = "high", motivation: str | None = "low", mode: str = "writing", planned: int = 30, started: str | None = "2026-07-15T09:00:00+03:00", blocked: bool | None = False) -> FeedbackObservation:
    return FeedbackObservation(1, f"o{index}", f"e{index}", "plans/p.md", "h", index, AS_OF - timedelta(days=index), "plan", "goal", "task", "Task", "shape", mode, "medium", "medium", blocked, outcome, 1.0 if outcome == "done" else 0.5 if outcome == "partial" else 0.0, planned, planned, energy, None, motivation, started, None, None, (), False)  # type: ignore[arg-type]


def test_energy_and_motivation_remain_distinct() -> None:
    items = tuple(observation(i, energy="high", motivation="low", outcome="done") for i in range(8)) + tuple(observation(20 + i, energy="low", motivation="high", outcome="skipped") for i in range(8))
    result = summarize_capacity_fit(observations=items, task_id="task", current_energy="high", current_motivation="high", mode="writing", declared_minutes=30, as_of=AS_OF)
    by_name = {item.name: item for item in result.dimensions}
    assert by_name["energy"].direction == "better_fit"
    assert by_name["motivation"].direction == "worse_fit"
    assert by_name["energy"].adjustment != by_name["motivation"].adjustment


def test_missing_and_disabled_dimensions_do_not_count_negative() -> None:
    items = tuple(observation(i, energy=None, motivation=None) for i in range(8))
    result = summarize_capacity_fit(observations=items, task_id="task", current_energy="medium", current_motivation="medium", mode="writing", declared_minutes=30, as_of=AS_OF, disabled_dimensions=("mode",))
    by_name = {item.name: item for item in result.dimensions}
    assert by_name["energy"].status == "insufficient"
    assert by_name["energy"].missing_count == 8
    assert by_name["mode"].status == "disabled"


def test_minimum_freshness_conflict_and_shuffle_boundaries() -> None:
    sparse = tuple(observation(i) for i in range(3))
    assert summarize_capacity_fit(observations=sparse, task_id="task", current_energy="high", current_motivation="low", mode="writing", declared_minutes=30, as_of=AS_OF).confidence == "insufficient"
    mixed = tuple(observation(i, outcome="done" if i % 2 else "skipped") for i in range(10))
    first = summarize_capacity_fit(observations=mixed, task_id="task", current_energy="high", current_motivation="low", mode="writing", declared_minutes=30, as_of=AS_OF)
    second = summarize_capacity_fit(observations=reversed(mixed), task_id="task", current_energy="high", current_motivation="low", mode="writing", declared_minutes=30, as_of=AS_OF)
    assert first == second
    assert any(item.status == "contradictory" for item in first.dimensions)


def test_explanations_are_noncausal_and_do_not_penalize_rest() -> None:
    items = tuple(observation(i) for i in range(8))
    result = summarize_capacity_fit(observations=items, task_id="hobby", current_energy="high", current_motivation="low", mode="writing", declared_minutes=30, as_of=AS_OF)
    text = " ".join(item.explanation for item in result.dimensions) + " " + result.caveat
    assert "noncausal" in text
    assert "discipline" in text
    assert "productivity score" not in text
