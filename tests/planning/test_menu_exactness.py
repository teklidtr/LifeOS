from __future__ import annotations

from datetime import date

from lifeos.planning import PlanningAction, build_daily_menu


def _action(
    task_id: str,
    duration: int,
    *,
    energy: str,
    due: date | None = None,
) -> PlanningAction:
    return PlanningAction(
        task_id=task_id,
        title=task_id,
        status="active",
        duration=duration,
        energy=energy,  # type: ignore[arg-type]
        motivation="medium",
        mode="desk",
        goal="goal",
        plan="plan-a",
        due=due,
        blocked_by=(),
        source_path=f"plans/{task_id}.md",
    )


def test_exact_solver_preserves_partial_states_whose_mean_fit_can_reverse() -> None:
    planning_day = date(2026, 7, 15)
    actions = (
        _action("a-single", 20, energy="high"),
        _action("b-first", 10, energy="high"),
        _action("b-second", 10, energy="medium"),
        _action("c-due", 10, energy="low", due=planning_day),
        _action("d-due", 10, energy="low", due=planning_day),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=planning_day,
        available_minutes=40,
        energy="high",
        motivation="medium",
    )

    assert menu.diagnostics.solver == "exact-dynamic-programming"
    assert {item.task_id for item in menu.items} == {
        "b-first",
        "b-second",
        "c-due",
        "d-due",
    }
    assert menu.diagnostics.selected_score[:4] == (90, 180, 1750, 3000)
