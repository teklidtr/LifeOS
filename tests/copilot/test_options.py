from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pytest

from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    PlanningSessionService,
    build_copilot_index,
    build_planning_context,
    generate_plan_options,
    parse_goal_note,
)
from lifeos.copilot.options import PlanOptionError, PlanOptionRequest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _goal(vault: Path, *, active_plans: str = "[]") -> None:
    _write(
        vault / "goals" / "cell.md",
        "---\n"
        "copilot_schema_version: 1\n"
        "id: goal-cell\n"
        "type: goal\n"
        "title: Learn cell biology\n"
        "status: active\n"
        "horizon: year\n"
        "why: Understand living systems.\n"
        "desired_change: Explain the first six chapters clearly.\n"
        "constraints: [Four hours weekly]\n"
        "non_goals: [Finish the entire textbook immediately]\n"
        f"active_plans: {active_plans}\n"
        "---\n",
    )


def _inputs(vault: Path):
    index = build_copilot_index(vault)
    goal = index.goals[0]
    service = PlanningSessionService(vault_root=vault, runtime_dir=vault / ".lifeos")
    snapshot = service.start(goal_path=goal.path, session_id="session-cell")
    context = build_planning_context(vault_root=vault, goal=goal, index=index)
    return goal, snapshot, context, index


class OptionsAdapter:
    def __init__(self, options: tuple[Mapping[str, Any], ...]) -> None:
        self.options = options

    def synthesize(self, request: PlanOptionRequest) -> tuple[Mapping[str, Any], ...]:
        assert request.schema_version == 1
        return self.options


def _raw_option(option_id: str, strategy: str, *, source_refs: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "option_id": option_id,
        "title": option_id.replace("-", " ").title(),
        "strategy": strategy,
        "desired_outcome": "Explain the first six chapters clearly.",
        "boundaries": ["Do not create a complete textbook backlog."],
        "assumptions": [
            {
                "assumption_id": f"assumption-{option_id}",
                "statement": "Four hours remain available each week.",
                "source_kind": "canonical-note",
                "source_ref": "goals/cell.md",
                "confidence": "medium",
            }
        ],
        "success_evidence": ["Six concise chapter synthesis notes."],
        "risks": ["The pace may be too dense."],
        "review_date": "2026-08-16",
        "milestones": [
            {
                "milestone_id": f"milestone-{option_id}",
                "title": "Build first foundation",
                "outcome": "Explain chapters one and two.",
                "wave": "current",
                "depends_on": [],
            }
        ],
        "tradeoffs": [f"Tradeoff for {strategy}"],
        "unresolved_questions": [],
        "source_refs": source_refs,
        "reasons_not_fit": ["May not match the preferred pace."],
        "confidence_label": "medium",
        "rejected_alternatives": [],
    }


def test_deterministic_fallback_returns_one_structured_option(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, snapshot, context, index = _inputs(tmp_path)
    result = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
    )
    assert result.outcome == "options"
    assert len(result.options) == 1
    assert result.options[0].milestones[0].wave == "current"
    assert result.options[0].review_date is None
    assert result.adapter_used is False


def test_adapter_can_return_meaningful_alternatives_or_no_option(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, snapshot, context, index = _inputs(tmp_path)
    refs = [item.path for item in context.items]
    options = (
        _raw_option("option-steady", "Steady weekly synthesis", source_refs=refs),
        _raw_option("option-experiment", "Two-week experiment before expansion", source_refs=refs),
        _raw_option("option-intensive", "Short intensive foundation sprint", source_refs=refs),
    )
    result = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
        adapter=OptionsAdapter(options),
    )
    assert [item.option_id for item in result.options] == [
        "option-steady",
        "option-experiment",
        "option-intensive",
    ]
    empty = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
        adapter=OptionsAdapter(()),
    )
    assert empty.outcome == "no-viable-option"


def test_experiment_decision_and_existing_plan_are_explicit_outcomes(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, snapshot, context, index = _inputs(tmp_path)
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    experiment = service.close(
        session_id="session-cell",
        outcome="experiment",
        label="Test study rhythm first",
        expected_revision=snapshot.envelope.session.source_revision,
    )
    result = generate_plan_options(
        goal=goal,
        session=experiment.envelope.session,
        readiness=experiment.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
    )
    assert result.outcome == "experiment-first"

    other = tmp_path / "other"
    _goal(other, active_plans="[plan-cell]")
    _write(
        other / "plans" / "cell.md",
        "---\nid: plan-cell\ntype: plan\ntitle: Learn cell biology\nstatus: active\ngoal: goal-cell\ndesired_outcome: Explain the first six chapters clearly.\n---\n",
    )
    goal2, snapshot2, context2, index2 = _inputs(other)
    linked = generate_plan_options(
        goal=goal2,
        session=snapshot2.envelope.session,
        readiness=snapshot2.envelope.readiness,
        context=context2,
        index=index2,
        as_of=date(2026, 7, 16),
    )
    assert linked.outcome == "link-existing-plan"
    assert linked.duplicate_findings[0].plan_id == "plan-cell"


def test_invalid_excessive_cosmetic_stale_and_hallucinated_output_is_rejected(
    tmp_path: Path,
) -> None:
    _goal(tmp_path)
    goal, snapshot, context, index = _inputs(tmp_path)
    refs = [item.path for item in context.items]
    with pytest.raises(PlanOptionError, match="more than three"):
        generate_plan_options(
            goal=goal,
            session=snapshot.envelope.session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=date(2026, 7, 16),
            adapter=OptionsAdapter(
                tuple(
                    _raw_option(f"option-{n}", f"Strategy {n}", source_refs=refs) for n in range(4)
                )
            ),
        )
    duplicate = _raw_option("option-a", "Same strategy", source_refs=refs)
    duplicate2 = _raw_option("option-b", "Same strategy", source_refs=refs)
    duplicate2["tradeoffs"] = duplicate["tradeoffs"]
    with pytest.raises(PlanOptionError, match="cosmetic"):
        generate_plan_options(
            goal=goal,
            session=snapshot.envelope.session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=date(2026, 7, 16),
            adapter=OptionsAdapter((duplicate, duplicate2)),
        )
    hallucinated = _raw_option(
        "option-hallucinated", "Distinct strategy", source_refs=["wiki/never-existed.md"]
    )
    with pytest.raises(PlanOptionError, match="unknown source"):
        generate_plan_options(
            goal=goal,
            session=snapshot.envelope.session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=date(2026, 7, 16),
            adapter=OptionsAdapter((hallucinated,)),
        )
    stale_goal = parse_goal_note(
        path=goal.path,
        content=(tmp_path / goal.path).read_text(encoding="utf-8") + "changed\n",
    )
    with pytest.raises(PlanOptionError, match="stale"):
        generate_plan_options(
            goal=stale_goal,
            session=snapshot.envelope.session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=date(2026, 7, 16),
        )


def test_near_duplicate_existing_plan_is_reported(tmp_path: Path) -> None:
    _goal(tmp_path)
    _write(
        tmp_path / "plans" / "archived.md",
        "---\nid: plan-old-cell\ntype: plan\ntitle: Learn cell biology foundation\nstatus: archived\ndesired_outcome: Explain the first six chapters clearly.\n---\n",
    )
    goal, snapshot, context, index = _inputs(tmp_path)
    result = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
    )
    assert result.duplicate_findings
    assert result.duplicate_findings[0].plan_id == "plan-old-cell"


def test_fixture_replay_and_bridge_are_deterministic(tmp_path: Path) -> None:
    _goal(tmp_path)
    app = BridgeApplication(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester"
    )
    app.dispatch(
        "copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"}
    )
    first = app.dispatch(
        "copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"}
    )
    second = app.dispatch(
        "copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"}
    )
    assert first == second
    assert first["outcome"] == "options"
