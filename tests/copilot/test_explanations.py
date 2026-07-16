from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    CopilotIndex, GoalReadinessReport, Milestone, PlanAssumption, PlanOption,
    PlanningContextItem, PlanningContextPack, ReadinessFinding,
    RecurringWorkload, check_portfolio_capacity, compare_plan_options,
    decompose_plan_option, explain_plan_option, recompute_capacity_counterfactual,
)
from lifeos.copilot.context import ContextOmission
from lifeos.copilot.explanations import ExplanationError


def _context(*, stale: bool = False, omitted: bool = False) -> PlanningContextPack:
    readiness = GoalReadinessReport(
        goal_id="goal-cell", source_path="goals/cell.md", source_hash=f"sha256:{'a'*64}",
        ready=True, path="plan", findings=(), active_plan_ids=(), missing_fields=(),
    )
    return PlanningContextPack(
        1, "goal-cell", f"sha256:{'a'*64}", readiness,
        (PlanningContextItem("goal-cell", "goals/cell.md", f"sha256:{'a'*64}", "selected goal", "Goal", 4, 4, False, (), "stale" if stale else "current", False),),
        (ContextOmission("journal/private.md", "explicitly-excluded", "Excluded"),) if omitted else (),
        4, False, True,
    )


def _option(option_id: str = "option-cell", *, source_ref: str = "goals/cell.md", assumption_kind: str = "canonical-note") -> PlanOption:
    return PlanOption(
        1, option_id, "Cell plan", "Use one bounded study wave", "Explain six chapters",
        ("Do not finish the whole book",),
        (PlanAssumption(f"assumption-{option_id}", "Four hours remain available", assumption_kind, source_ref if assumption_kind != "agent-assumption" else None, "medium"),),
        ("Six notes",), ("Pace may be dense",), None,
        (Milestone(f"milestone-{option_id}", "Build foundation", "Explain two chapters", wave="current"),),
        ("Narrow scope",), ("Is four hours realistic?",), (source_ref,), confidence_label="medium",
    )


def _bundle(option: PlanOption, minutes: int | None = 300):
    decomposition = decompose_plan_option(option=option, horizon="months")
    capacity = check_portfolio_capacity(option=option, decomposition=decomposition, index=CopilotIndex((), (), ()), as_of=date(2026, 7, 16), available_minutes=minutes, recurring_workloads=(RecurringWorkload("rest", "Rest", 60, "rest"),))
    return decomposition, capacity


def test_explanation_distinguishes_sources_assumptions_stale_and_omissions() -> None:
    option = _option(assumption_kind="agent-assumption")
    decomp, capacity = _bundle(option)
    result = explain_plan_option(option=option, decomposition=decomp, capacity=capacity, context=_context(stale=True, omitted=True))
    states = {p.evidence_state for item in result.items for p in item.provenance}
    assert {"stale", "assumption"} <= states
    assert result.omissions[0].reason == "explicitly-excluded"
    assert "hidden" in result.summary


def test_invalid_explanation_reference_is_rejected() -> None:
    option = _option(source_ref="deleted/missing.md")
    decomp, capacity = _bundle(option)
    with pytest.raises(ExplanationError, match="invalid explanation source"):
        explain_plan_option(option=option, decomposition=decomp, capacity=capacity, context=_context())


def test_comparison_uses_explicit_dimensions_and_no_winner() -> None:
    a, b = _option("option-a"), _option("option-b")
    da, ca = _bundle(a, 400)
    db, cb = _bundle(b, 100)
    result = compare_plan_options(options=(b, a), decompositions={a.option_id: da, b.option_id: db}, capacity_reports={a.option_id: ca, b.option_id: cb})
    assert result.option_ids == ("option-a", "option-b")
    assert [item.dimension for item in result.dimensions] == ["scope", "pace", "uncertainty", "capacity-fit", "risks", "reversible-first-step", "unresolved-questions"]
    assert "No winner" in result.criteria_note


def test_counterfactual_is_recomputed_not_improvised() -> None:
    option = _option()
    decomp, before = _bundle(option, 400)
    result = recompute_capacity_counterfactual(option=option, decomposition=decomp, index=CopilotIndex((), (), ()), before=before, as_of=date(2026, 7, 16), available_minutes=50)
    assert result.before_fit == "comfortable"
    assert result.after_fit == "overload"
    assert result.report.baseline.available_minutes == 50


def test_stable_serialization() -> None:
    option = _option()
    decomp, capacity = _bundle(option)
    first = explain_plan_option(option=option, decomposition=decomp, capacity=capacity, context=_context()).to_dict()
    second = explain_plan_option(option=option, decomposition=decomp, capacity=capacity, context=_context()).to_dict()
    assert first == second


def test_bridge_exposes_explanation_and_counterfactual(tmp_path: Path) -> None:
    goal = tmp_path / "goals" / "cell.md"
    goal.parent.mkdir(parents=True)
    goal.write_text("---\ncopilot_schema_version: 1\nid: goal-cell\ntype: goal\ntitle: Learn cells\nstatus: active\nhorizon: year\nwhy: Understand cells.\ndesired_change: Explain six chapters.\nconstraints: [Four hours weekly]\n---\n", encoding="utf-8")
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    app.dispatch("copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"})
    options = app.dispatch("copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"})
    option_id = options["options"][0]["option_id"]
    explanation = app.dispatch("copilot.explain", {"session_id": "session-cell", "option_id": option_id, "as_of": "2026-07-16", "available_minutes": 300})
    counter = app.dispatch("copilot.counterfactual", {"session_id": "session-cell", "option_id": option_id, "as_of": "2026-07-16", "before_available_minutes": 300, "available_minutes": 30})
    comparison = app.dispatch("copilot.compare", {"session_id": "session-cell", "option_ids": [option_id], "as_of": "2026-07-16", "available_minutes": 300})
    assert explanation["items"]
    assert counter["after_fit"] in {"marginal", "overload"}
    assert comparison["dimensions"]
