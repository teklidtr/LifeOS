from __future__ import annotations

from datetime import date, timedelta

from lifeos.feedback import FeedbackObservation, build_adaptive_menu
from lifeos.planning import PlanningAction

AS_OF = date(2026, 7, 16)


def action(task: str, duration: int, *, due: date | None = None, energy: str = "medium", motivation: str = "medium") -> PlanningAction:
    return PlanningAction(task, task.title(), "todo", duration, energy, motivation, "writing", "goal", "plan", due, (), "plans/p.md")  # type: ignore[arg-type]


def event(index: int, task: str, *, planned: int, actual: int, outcome: str = "done", energy: str = "medium", motivation: str = "medium") -> FeedbackObservation:
    return FeedbackObservation(1, f"o{index}", f"e{index}", "plans/p.md", "h", index, AS_OF - timedelta(days=index), "plan", "goal", task, task, "unspecified", "writing", "medium", "medium", False, outcome, 1.0 if outcome == "done" else 0.0, planned, actual, energy, None, motivation, None, None, None, (), False)  # type: ignore[arg-type]


def test_no_evidence_and_off_mode_match_baseline_exactly() -> None:
    actions = (action("a", 30), action("b", 45))
    result = build_adaptive_menu(actions=actions, observations=(), as_of=AS_OF, available_minutes=60, energy="medium", motivation="medium", adaptive_mode="off")
    assert result.baseline == result.adaptive == result.returned
    assert result.feedback_status == "insufficient"


def test_shadow_computes_difference_but_returns_baseline() -> None:
    actions = (action("a", 30), action("b", 30))
    history = tuple(event(i, "a", planned=30, actual=60) for i in range(6))
    result = build_adaptive_menu(actions=actions, observations=history, as_of=AS_OF, available_minutes=60, energy="medium", motivation="medium", adaptive_mode="shadow")
    assert result.returned == result.baseline
    assert result.adaptive != result.baseline
    assert any(delta.effective_minutes != delta.declared_minutes for delta in result.deltas)


def test_active_respects_capacity_and_explicit_due_priority() -> None:
    actions = (action("urgent", 30, due=AS_OF), action("learned", 30))
    history = tuple(event(i, "learned", planned=30, actual=60) for i in range(6))
    result = build_adaptive_menu(actions=actions, observations=history, as_of=AS_OF, available_minutes=60, energy="medium", motivation="medium", adaptive_mode="active")
    returned = result.returned
    assert returned["selected_minutes"] <= 60
    assert any(item["task_id"] == "urgent" for item in returned["items"])


def test_blocked_completed_mode_and_energy_constraints_remain_authoritative() -> None:
    actions = (
        PlanningAction("blocked", "Blocked", "todo", 10, "low", "low", "writing", "g", "p", None, ("missing",), "plans/p.md"),
        PlanningAction("done", "Done", "done", 10, "low", "low", "writing", "g", "p", None, (), "plans/p.md"),
        PlanningAction("high", "High", "todo", 10, "high", "low", "writing", "g", "p", None, (), "plans/p.md"),
    )
    history = tuple(event(i, "blocked", planned=10, actual=1) for i in range(10))
    result = build_adaptive_menu(actions=actions, observations=history, as_of=AS_OF, available_minutes=60, energy="low", motivation="low", adaptive_mode="active")
    assert result.returned["items"] == ()


def test_disabled_feedback_and_shuffle_are_deterministic() -> None:
    actions = (action("a", 30), action("b", 30))
    history = tuple(event(i, "a", planned=30, actual=45) for i in range(8))
    first = build_adaptive_menu(actions=actions, observations=history, as_of=AS_OF, available_minutes=60, energy="medium", motivation="medium", adaptive_mode="active", disabled_dimensions=("duration", "energy", "motivation", "mode", "duration_band", "time_window", "blocker"))
    second = build_adaptive_menu(actions=tuple(reversed(actions)), observations=reversed(history), as_of=AS_OF, available_minutes=60, energy="medium", motivation="medium", adaptive_mode="active", disabled_dimensions=("duration", "energy", "motivation", "mode", "duration_band", "time_window", "blocker"))
    assert first == second
    assert first.returned == first.baseline
