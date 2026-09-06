from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from lifeos.feedback import FeedbackObservation, build_adaptive_menu, explain_adaptive_result
from lifeos.planning import PlanningAction

AS_OF = date(2026, 7, 16)


def action(
    task: str, duration: int, *, energy: str = "medium", mode: str = "writing"
) -> PlanningAction:
    return PlanningAction(
        task,
        task.title(),
        "todo",
        duration,
        energy,
        "medium",
        mode,
        "goal",
        "plan",
        None,
        (),
        "plans/p.md",
    )  # type: ignore[arg-type]


def event(index: int, task: str, actual: int) -> FeedbackObservation:
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
        task,
        "unspecified",
        "writing",
        "medium",
        "medium",
        False,
        "done",
        1.0,
        30,
        actual,
        "medium",
        None,
        "medium",
        None,
        None,
        None,
        (),
        False,
    )


def test_selected_explanation_matches_exact_result_and_serializes() -> None:
    actions = (action("a", 30), action("b", 30))
    history = tuple(event(i, "a", 45) for i in range(6))
    result = build_adaptive_menu(
        actions=actions,
        observations=history,
        as_of=AS_OF,
        available_minutes=60,
        energy="medium",
        motivation="medium",
        adaptive_mode="active",
    )
    explanation = explain_adaptive_result(result=result, actions=actions, task_id="a")
    assert explanation.selected_in_baseline is True
    assert explanation.declared_minutes == 30
    assert explanation.effective_minutes >= 30
    assert "duration-calibrated" in explanation.reason_codes
    assert json.loads(json.dumps(explanation.to_dict(), default=str))["task_id"] == "a"


def test_rejected_candidate_gets_time_energy_mode_and_evidence_counterfactuals() -> None:
    actions = (action("large", 90, energy="high", mode="deep"),)
    result = build_adaptive_menu(
        actions=actions,
        observations=(),
        as_of=AS_OF,
        available_minutes=30,
        energy="low",
        motivation="medium",
        adaptive_mode="active",
    )
    explanation = explain_adaptive_result(result=result, actions=actions, task_id="large")
    codes = {item.code for item in explanation.counterfactuals}
    assert {"available-time", "time-shortfall", "energy", "mode", "evidence"} <= codes
    assert "not-selected" in explanation.reason_codes


def test_disabled_low_confidence_signals_are_named_without_private_text() -> None:
    actions = (action("a", 30),)
    result = build_adaptive_menu(
        actions=actions,
        observations=(event(1, "a", 50),),
        as_of=AS_OF,
        available_minutes=30,
        energy="medium",
        motivation="medium",
        adaptive_mode="shadow",
        disabled_dimensions=("energy", "motivation"),
    )
    explanation = explain_adaptive_result(result=result, actions=actions, task_id="a")
    assert "energy:disabled" in explanation.ignored_signals
    assert "motivation:disabled" in explanation.ignored_signals
    assert "journal" not in " ".join(explanation.expanded).casefold()
    assert "unrelated journal prose" in explanation.privacy


def test_deterministic_order_and_unknown_task() -> None:
    actions = (action("a", 30), action("b", 30))
    history = tuple(event(i, "a", 45) for i in range(6))
    first_result = build_adaptive_menu(
        actions=actions,
        observations=history,
        as_of=AS_OF,
        available_minutes=30,
        energy="medium",
        motivation="medium",
        adaptive_mode="active",
    )
    second_result = build_adaptive_menu(
        actions=tuple(reversed(actions)),
        observations=reversed(history),
        as_of=AS_OF,
        available_minutes=30,
        energy="medium",
        motivation="medium",
        adaptive_mode="active",
    )
    assert explain_adaptive_result(
        result=first_result, actions=actions, task_id="a"
    ) == explain_adaptive_result(result=second_result, actions=actions, task_id="a")
    with pytest.raises(KeyError):
        explain_adaptive_result(result=first_result, actions=actions, task_id="missing")
