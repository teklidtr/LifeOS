from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.planning import (
    PlanningAction,
    PlanningError,
    build_daily_menu,
    format_daily_menu,
    load_plan_actions,
)


def test_load_plan_actions_from_frontmatter(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "biology.md").write_text(
        "---\n"
        "type: plan\n"
        "id: plan-biology\n"
        "goal: goal-learn-biology\n"
        "tasks:\n"
        "  - task_id: task-read\n"
        "    title: Read one chapter\n"
        "    status: active\n"
        "    duration: 45\n"
        "    energy: medium\n"
        "    motivation: high\n"
        "    mode: deep-work\n"
        "    due: 2026-07-20\n"
        "    blocked_by: []\n"
        "---\n",
        encoding="utf-8",
    )

    actions = load_plan_actions(tmp_path)

    assert len(actions) == 1
    assert actions[0].task_id == "task-read"
    assert actions[0].plan == "plan-biology"
    assert actions[0].goal == "goal-learn-biology"


def test_daily_menu_enforces_blockers_energy_and_budget() -> None:
    actions = (
        PlanningAction(
            "done",
            "Finished prerequisite",
            "done",
            10,
            "low",
            "low",
            "admin",
            "goal",
            "plan-a",
            None,
            (),
            "plans/a.md",
        ),
        PlanningAction(
            "eligible",
            "Eligible task",
            "active",
            30,
            "medium",
            "high",
            "deep",
            "goal",
            "plan-a",
            date(2026, 7, 15),
            ("done",),
            "plans/a.md",
        ),
        PlanningAction(
            "blocked",
            "Blocked task",
            "active",
            15,
            "low",
            "high",
            "admin",
            "goal",
            "plan-b",
            None,
            ("missing",),
            "plans/b.md",
        ),
        PlanningAction(
            "too-hard",
            "High energy task",
            "active",
            20,
            "high",
            "high",
            "deep",
            "goal",
            "plan-c",
            None,
            (),
            "plans/c.md",
        ),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=40,
        energy="medium",
        motivation="low",
    )

    assert [item.task_id for item in menu.items] == ["eligible"]
    reasons = {item.task_id: item.reason for item in menu.deferred}
    assert reasons["blocked"] == "blocked by missing"
    assert reasons["too-hard"] == "requires more energy than available"
    assert "low motivation" in menu.items[0].reason


def test_overdue_actions_rank_before_undated_actions() -> None:
    actions = (
        PlanningAction(
            "later",
            "Undated",
            "active",
            20,
            "low",
            "medium",
            "desk",
            "goal",
            "plan-a",
            None,
            (),
            "plans/a.md",
        ),
        PlanningAction(
            "overdue",
            "Overdue",
            "active",
            20,
            "low",
            "medium",
            "desk",
            "goal",
            "plan-b",
            date(2026, 7, 1),
            (),
            "plans/b.md",
        ),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=20,
        energy="low",
        motivation="medium",
    )

    assert menu.items[0].task_id == "overdue"
    assert menu.deferred[0].task_id == "later"


def test_invalid_duplicate_task_ids_are_rejected(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    template = (
        "---\ntype: plan\ntasks:\n"
        "  - task_id: duplicate\n"
        "    title: Task\n"
        "    status: active\n"
        "    duration: 10\n"
        "    energy: low\n"
        "    motivation: low\n"
        "    mode: desk\n"
        "    blocked_by: []\n---\n"
    )
    (plans / "a.md").write_text(template, encoding="utf-8")
    (plans / "b.md").write_text(template, encoding="utf-8")

    with pytest.raises(PlanningError, match="unique"):
        load_plan_actions(tmp_path)


@pytest.mark.parametrize(
    "task_fragment",
    [
        "    energy:\n      - low\n",
        "    goal: 42\n",
        "    plan: 42\n",
        "    blocked_by:\n      - '   '\n",
    ],
)
def test_plan_actions_reject_malformed_typed_fields(
    tmp_path: Path,
    task_fragment: str,
) -> None:
    plan = tmp_path / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\n"
        "type: plan\n"
        "tasks:\n"
        "  - task_id: task-one\n"
        "    title: Broken action\n"
        "    status: active\n"
        "    duration: 30\n"
        "    mode: desk\n"
        f"{task_fragment}"
        "---\n",
        encoding="utf-8",
    )

    with pytest.raises(PlanningError):
        load_plan_actions(tmp_path)


def test_plan_actions_normalize_blocker_ids(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\n"
        "type: plan\n"
        "tasks:\n"
        "  - task_id: task-one\n"
        "    title: Action\n"
        "    status: active\n"
        "    duration: 30\n"
        "    mode: desk\n"
        "    blocked_by:\n"
        "      - ' task-zero '\n"
        "---\n",
        encoding="utf-8",
    )

    actions = load_plan_actions(tmp_path)

    assert actions[0].blocked_by == ("task-zero",)


def test_daily_menu_normalizes_capacity_levels_and_mode() -> None:
    action = PlanningAction(
        task_id="task-one",
        title="Read",
        status="active",
        duration=30,
        energy="low",
        motivation="medium",
        mode="Desk",
        goal="Learn",
        plan="study",
        due=None,
        blocked_by=(),
        source_path="plans/study.md",
    )

    menu = build_daily_menu(
        actions=(action,),
        as_of=date(2026, 7, 15),
        available_minutes=30,
        energy=" Low ",
        motivation=" MEDIUM ",
        mode=" desk ",
    )

    assert menu.energy == "low"
    assert menu.motivation == "medium"
    assert [item.task_id for item in menu.items] == ["task-one"]


def test_daily_menu_rejects_blank_mode() -> None:
    with pytest.raises(PlanningError, match="mode must be a non-empty string"):
        build_daily_menu(
            actions=(),
            as_of=date(2026, 7, 15),
            available_minutes=30,
            energy="low",
            motivation="medium",
            mode="   ",
        )


def test_plan_action_due_rejects_datetime_metadata(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\n"
        "type: plan\n"
        "tasks:\n"
        "  - task_id: task-one\n"
        "    title: Action\n"
        "    status: active\n"
        "    duration: 30\n"
        "    mode: desk\n"
        "    due: 2026-07-01T12:00:00\n"
        "---\n",
        encoding="utf-8",
    )

    with pytest.raises(PlanningError, match="due must be an ISO date"):
        load_plan_actions(tmp_path)


def _optimizer_action(
    task_id: str,
    duration: int,
    *,
    due: date | None = date(2026, 7, 1),
    plan: str = "plan-a",
    energy: str = "low",
    motivation: str = "medium",
) -> PlanningAction:
    return PlanningAction(
        task_id=task_id,
        title=task_id,
        status="active",
        duration=duration,
        energy=energy,  # type: ignore[arg-type]
        motivation=motivation,  # type: ignore[arg-type]
        mode="desk",
        goal="goal",
        plan=plan,
        due=due,
        blocked_by=(),
        source_path=f"plans/{task_id}.md",
    )


def test_daily_menu_optimizer_beats_greedy_capacity_counterexample() -> None:
    actions = (
        _optimizer_action("a-long", 70),
        _optimizer_action("b-short", 40, plan="plan-b"),
        _optimizer_action("c-short", 40, plan="plan-c"),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=80,
        energy="low",
        motivation="medium",
    )

    assert {item.task_id for item in menu.items} == {"b-short", "c-short"}
    assert menu.selected_minutes == 80
    assert menu.diagnostics.solver == "exact-dynamic-programming"


def test_daily_menu_optimizer_keeps_highest_urgency_action() -> None:
    actions = (
        _optimizer_action("critical", 70, due=date(2026, 6, 1)),
        _optimizer_action("today-a", 40, due=date(2026, 7, 15), plan="plan-b"),
        _optimizer_action("today-b", 40, due=date(2026, 7, 15), plan="plan-c"),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=80,
        energy="low",
        motivation="medium",
    )

    assert "critical" in {item.task_id for item in menu.items}
    assert menu.diagnostics.objective_order[:4] == (
        "maximum due urgency",
        "total due urgency",
        "mean energy fit",
        "mean motivation fit",
    )


def test_daily_menu_capacity_is_ceiling_not_fill_target() -> None:
    actions = (
        _optimizer_action("critical", 30, due=date(2026, 7, 15), plan="plan-a"),
        _optimizer_action("optional-a", 20, due=None, plan="plan-b"),
        _optimizer_action("optional-b", 20, due=None, plan="plan-c"),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=100,
        energy="low",
        motivation="medium",
    )

    assert [item.task_id for item in menu.items] == ["critical"]
    assert menu.selected_minutes == 30
    assert menu.diagnostics.unused_minutes == 70
    assert "capacity used" not in menu.diagnostics.objective_order
    assert "item count" not in menu.diagnostics.objective_order
    rendered = format_daily_menu(menu)
    assert "Capacity ceiling: 100 min" in rendered
    assert "remaining: 70 min" in rendered
    assert "unused:" not in rendered


def test_daily_menu_increasing_capacity_alone_does_not_expand_workload() -> None:
    actions = (
        _optimizer_action("critical", 30, due=date(2026, 7, 15)),
        _optimizer_action("optional", 20, due=None, plan="plan-b"),
    )

    tight = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=30,
        energy="low",
        motivation="medium",
    )
    roomy = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=120,
        energy="low",
        motivation="medium",
    )

    assert [item.task_id for item in tight.items] == ["critical"]
    assert [item.task_id for item in roomy.items] == ["critical"]


def test_daily_menu_equivalent_optional_work_prefers_lower_workload_before_id() -> None:
    actions = (
        _optimizer_action("a-long", 40, due=None),
        _optimizer_action("z-short", 20, due=None),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=60,
        energy="low",
        motivation="medium",
    )

    assert [item.task_id for item in menu.items] == ["z-short"]
    assert menu.selected_minutes == 20


def test_daily_menu_additive_urgency_can_justify_more_work() -> None:
    actions = (
        _optimizer_action("due-a", 30, due=date(2026, 7, 15)),
        _optimizer_action("due-b", 30, due=date(2026, 7, 15)),
        _optimizer_action("optional", 20, due=None, plan="plan-b"),
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=100,
        energy="low",
        motivation="medium",
    )

    assert [item.task_id for item in menu.items] == ["due-a", "due-b"]
    assert menu.selected_minutes == 60


def test_daily_menu_mean_fit_is_size_neutral_and_dimensions_remain_distinct() -> None:
    one = (_optimizer_action("due-a", 20, energy="low", motivation="high"),)
    two = (
        *one,
        _optimizer_action("due-b", 20, energy="low", motivation="high"),
    )

    one_menu = build_daily_menu(
        actions=one,
        as_of=date(2026, 7, 15),
        available_minutes=40,
        energy="low",
        motivation="low",
    )
    two_menu = build_daily_menu(
        actions=two,
        as_of=date(2026, 7, 15),
        available_minutes=40,
        energy="low",
        motivation="low",
    )

    assert one_menu.diagnostics.selected_score[2:4] == (3000, 1000)
    assert two_menu.diagnostics.selected_score[2:4] == (3000, 1000)


def test_daily_menu_optimizer_is_stable_under_shuffled_candidates() -> None:
    actions = tuple(
        _optimizer_action(f"task-{index}", 20 + index, plan=f"plan-{index % 3}")
        for index in range(8)
    )

    first = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=90,
        energy="low",
        motivation="medium",
    )
    second = build_daily_menu(
        actions=tuple(reversed(actions)),
        as_of=date(2026, 7, 15),
        available_minutes=90,
        energy="low",
        motivation="medium",
    )

    assert first == second


def test_daily_menu_optimizer_supports_zero_and_maximum_capacity() -> None:
    action = _optimizer_action("task", 10)

    empty = build_daily_menu(
        actions=(action,),
        as_of=date(2026, 7, 15),
        available_minutes=0,
        energy="low",
        motivation="medium",
    )
    maximum = build_daily_menu(
        actions=(action,),
        as_of=date(2026, 7, 15),
        available_minutes=1440,
        energy="low",
        motivation="medium",
    )

    assert empty.items == ()
    assert empty.diagnostics.unused_minutes == 0
    assert len(maximum.items) == 1
    with pytest.raises(PlanningError, match="0 to 1440"):
        build_daily_menu(
            actions=(action,),
            as_of=date(2026, 7, 15),
            available_minutes=1441,
            energy="low",
            motivation="medium",
        )


def test_daily_menu_optimizer_uses_deterministic_fallback_above_bound() -> None:
    actions = tuple(
        _optimizer_action(f"task-{index:02d}", 10, plan=f"plan-{index % 4}") for index in range(21)
    )

    menu = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=50,
        energy="low",
        motivation="medium",
    )

    assert menu.diagnostics.solver == "deterministic-bounded-fallback"
    assert "exact solver candidate limit (20)" in menu.diagnostics.binding_constraints
    assert len(menu.items) == 5


def test_daily_menu_fallback_uses_same_capacity_ceiling_policy() -> None:
    actions = (
        _optimizer_action("critical", 30, due=date(2026, 7, 15)),
        *tuple(
            _optimizer_action(f"optional-{index:02d}", 10, due=None, plan=f"plan-{index % 4}")
            for index in range(20)
        ),
    )

    first = build_daily_menu(
        actions=actions,
        as_of=date(2026, 7, 15),
        available_minutes=100,
        energy="low",
        motivation="medium",
    )
    second = build_daily_menu(
        actions=tuple(reversed(actions)),
        as_of=date(2026, 7, 15),
        available_minutes=100,
        energy="low",
        motivation="medium",
    )

    assert first.diagnostics.solver == "deterministic-bounded-fallback"
    assert [item.task_id for item in first.items] == ["critical"]
    assert first == second
