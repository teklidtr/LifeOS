from __future__ import annotations

from datetime import date
from pathlib import Path

from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    CopilotIndex,
    GoalRecord,
    Milestone,
    NearTermAction,
    PlanOption,
    PlanRecord,
    RecurringWorkload,
    check_portfolio_capacity,
    decompose_plan_option,
)
from lifeos.copilot.decomposition import ActionSuggestion


class Adapter:
    def __init__(self, actions: tuple[ActionSuggestion, ...]) -> None:
        self.actions = actions

    def decompose(self, **_: object) -> tuple[ActionSuggestion, ...]:
        return self.actions


def _option(outcome: str = "Explain six cell biology chapters") -> PlanOption:
    return PlanOption(
        1, "option-cell", "Cell plan", "Study in a bounded wave", outcome,
        ("Protect exercise and rest",), (), ("Six notes",), ("Pace risk",), None,
        (Milestone("milestone-cell", "Build foundation", "Explain two chapters", wave="current"),),
        ("Narrow scope",), (), ("goals/cell.md",), confidence_label="medium",
    )


def _action(task_id: str, minutes: int | None = 60, *, due: date | None = None, blocked_by: tuple[str, ...] = ()) -> ActionSuggestion:
    return ActionSuggestion(
        title=f"Complete bounded work for {task_id}", task_id=task_id,
        milestone_id="milestone-cell", duration=minutes, energy="medium",
        motivation="medium", mode="study", due=due, blocked_by=blocked_by,
        rationale="Visible first step", verification="A visible note", source_refs=("goals/cell.md",),
    )


def _index(plans: tuple[PlanRecord, ...] = ()) -> CopilotIndex:
    return CopilotIndex((), plans, ())


def _plan(plan_id: str, *, outcome: str = "Different outcome", tasks: tuple[NearTermAction, ...] = ()) -> PlanRecord:
    return PlanRecord(1, plan_id, plan_id, "active", f"plans/{plan_id}.md", f"sha256:{'a'*64}", desired_outcome=outcome, tasks=tasks)


def test_comfortable_marginal_overload_and_unknown_capacity() -> None:
    option = _option()
    decomp = decompose_plan_option(option=option, horizon="months", adapter=Adapter((_action("task-new", 60),)))
    protected = (RecurringWorkload("run", "Running", 60, kind="exercise"),)
    comfortable = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(), as_of=date(2026, 7, 16), available_minutes=600, recurring_workloads=protected)
    marginal = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(), as_of=date(2026, 7, 16), available_minutes=150, recurring_workloads=protected)
    overload = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(), as_of=date(2026, 7, 16), available_minutes=100, recurring_workloads=protected)
    unknown = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(), as_of=date(2026, 7, 16), available_minutes=None)
    assert [comfortable.fit, marginal.fit, overload.fit, unknown.fit] == ["comfortable", "marginal", "overload", "unknown"]
    assert any(item.code == "capacity-overload" for item in overload.findings)
    assert any(item.code == "recurring-workload-data-missing" for item in unknown.findings)


def test_missing_duration_is_unknown_not_zero_and_adaptive_view_stays_separate() -> None:
    option = _option()
    decomp = decompose_plan_option(option=option, horizon="months", adapter=Adapter((_action("task-new", None),)))
    report = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(), as_of=date(2026, 7, 16), available_minutes=100, adaptive_durations={"task-new": 120})
    assert report.baseline.fit == "unknown"
    assert report.adaptive is not None and report.adaptive.fit == "overload"
    assert any(item.code == "baseline-adaptive-difference" for item in report.findings)


def test_due_prerequisite_duplicate_and_many_plan_findings_are_inspectable() -> None:
    due = date(2026, 7, 20)
    option = _option()
    decomp = decompose_plan_option(option=option, horizon="months", adapter=Adapter((
        _action("task-a", 80, due=due, blocked_by=("task-prereq",)),
        _action("task-b", 80, due=due, blocked_by=("task-prereq",)),
    )), explicit_deadlines={"task-a": due, "task-b": due}, existing_task_ids=("task-prereq",))
    existing = NearTermAction("task-existing", "Existing deadline", duration=80, due=due)
    plans = (_plan("plan-duplicate", outcome="Explain six cell biology chapters", tasks=(existing,)),) + tuple(_plan(f"plan-{i}") for i in range(2, 8))
    report = check_portfolio_capacity(option=option, decomposition=decomp, index=_index(plans), as_of=date(2026, 7, 16), available_minutes=200)
    codes = {item.code for item in report.findings}
    assert {"due-date-contention", "competing-prerequisite", "duplicate-outcome", "active-plan-count-high"} <= codes
    assert all(item.possible_adjustments for item in report.findings if item.severity != "information")


def test_stable_under_shuffled_inputs() -> None:
    option = _option()
    decomp = decompose_plan_option(option=option, horizon="months", adapter=Adapter((_action("task-new", 60),)))
    workloads = (RecurringWorkload("b", "Rest", 30, kind="rest"), RecurringWorkload("a", "Hobby", 30, kind="hobby"))
    first = check_portfolio_capacity(option=option, decomposition=decomp, index=_index((_plan("plan-b"), _plan("plan-a"))), as_of=date(2026, 7, 16), available_minutes=500, recurring_workloads=workloads)
    second = check_portfolio_capacity(option=option, decomposition=decomp, index=_index((_plan("plan-a"), _plan("plan-b"))), as_of=date(2026, 7, 16), available_minutes=500, recurring_workloads=tuple(reversed(workloads)))
    assert first.to_dict() == second.to_dict()


def test_bridge_exposes_read_only_capacity_check(tmp_path: Path) -> None:
    goal = tmp_path / "goals" / "cell.md"
    goal.parent.mkdir(parents=True)
    goal.write_text("---\ncopilot_schema_version: 1\nid: goal-cell\ntype: goal\ntitle: Learn cells\nstatus: active\nhorizon: year\nwhy: Understand cells.\ndesired_change: Explain six chapters.\nconstraints: [Four hours weekly]\n---\n", encoding="utf-8")
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    app.dispatch("copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"})
    options = app.dispatch("copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"})
    result = app.dispatch("copilot.capacity.check", {"session_id": "session-cell", "option_id": options["options"][0]["option_id"], "as_of": "2026-07-16", "available_minutes": 300, "recurring_workloads": [{"workload_id": "run", "title": "Running", "minutes": 60, "kind": "exercise"}]})
    assert result["fit"] in {"comfortable", "marginal", "overload", "unknown"}
    assert "score" not in result
