from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.copilot import (
    CopilotContractError,
    Milestone,
    NearTermAction,
    PlanningAnswer,
    PlanningSession,
    build_copilot_index,
    compatibility_diagnostics,
    inspect_copilot_note,
    parse_goal_note,
    parse_plan_note,
)
from lifeos.bridge import BridgeApplication


def _goal(*, extra: str = "") -> str:
    return f"""---
copilot_schema_version: 1
id: goal-learn-cell
 type: invalid
---
""".replace(" type: invalid", "type: goal") + extra


def test_minimal_legacy_goal_preserves_unknown_values() -> None:
    goal = parse_goal_note(
        path="goals/cell.md",
        content="""---
id: goal-cell
type: goal
title: Learn cell biology
status: active
---
Direction, not a task warehouse.
""",
    )
    assert goal.schema_version == 0
    assert goal.horizon is None
    assert goal.desired_change is None
    assert goal.constraints == ()


def test_fully_populated_goal_and_plan() -> None:
    goal = parse_goal_note(
        path="goals/cell.md",
        content="""---
copilot_schema_version: 1
id: goal-cell
type: goal
title: Learn cell biology
status: active
description: Build a durable foundation.
horizon: year
why: Understand living systems.
desired_change: Explain core cell mechanisms.
constraints: [Four hours weekly]
non_goals: [Finish every chapter immediately]
review_cadence: monthly
readiness: ready
active_plans: [plan-cell-foundations]
---
""",
    )
    plan = parse_plan_note(
        path="plans/cell.md",
        content="""---
copilot_schema_version: 1
id: plan-cell-foundations
type: plan
title: Cell foundations
status: active
goal: goal-cell
desired_outcome: Explain chapters one through three.
success_evidence: [Three synthesis notes]
boundaries: [No complete textbook backlog]
assumptions: [Four hours weekly remains available]
review_date: 2026-08-16
rolling_wave_depth: 2
milestones:
  - milestone_id: milestone-cell-1
    title: Build foundations
    outcome: Explain membrane and organelle basics.
    wave: current
tasks:
  - task_id: task-cell-read-1
    title: Read and annotate chapter one
    status: todo
    duration: 60
    energy: medium
    motivation: medium
    mode: study
    milestone_id: milestone-cell-1
    blocked_by: []
    source_refs: [goal-cell]
---
""",
    )
    assert goal.horizon == "year"
    assert plan.review_date == date(2026, 8, 16)
    assert plan.tasks[0].milestone_id == plan.milestones[0].milestone_id


def test_invalid_contract_values_are_rejected() -> None:
    with pytest.raises(CopilotContractError, match="unsupported goal horizon"):
        parse_goal_note(
            path="goals/bad.md",
            content="""---
copilot_schema_version: 1
id: goal-bad
type: goal
title: Bad
status: active
horizon: tomorrow-at-9
---
""",
        )
    with pytest.raises(CopilotContractError, match="duration"):
        NearTermAction(task_id="task-bad", title="Bad", duration=0)
    with pytest.raises(CopilotContractError, match="unknown milestone"):
        from lifeos.copilot import PlanRecord

        PlanRecord(
            schema_version=1,
            plan_id="plan-bad",
            title="Bad",
            status="active",
            path="plans/bad.md",
            content_hash="sha256:x",
            milestones=(),
            tasks=(
                NearTermAction(
                    task_id="task-bad",
                    title="Bad",
                    milestone_id="milestone-missing",
                ),
            ),
        )


def test_unknown_empty_and_not_relevant_are_distinct() -> None:
    session = PlanningSession(
        schema_version=1,
        session_id="session-1",
        goal_ref="goals/cell.md",
        goal_hash="sha256:abc",
        status="clarifying",
        answers=(
            PlanningAnswer("purpose", "unknown"),
            PlanningAnswer("budget", "not-relevant"),
            PlanningAnswer("horizon", "skipped"),
        ),
    )
    restored = PlanningSession.from_dict(session.to_dict())
    assert [answer.response_kind for answer in restored.answers] == [
        "unknown",
        "not-relevant",
        "skipped",
    ]
    with pytest.raises(CopilotContractError, match="visible value"):
        PlanningAnswer("purpose", "answered")


def test_duplicate_ids_and_relationship_diagnostics_are_deterministic(tmp_path: Path) -> None:
    vault = tmp_path
    (vault / "goals").mkdir()
    (vault / "plans").mkdir()
    (vault / "goals" / "a.md").write_text(
        "---\nid: same-id\ntype: goal\ntitle: A\nstatus: active\nactive_plans: [missing-plan]\n---\n",
        encoding="utf-8",
    )
    (vault / "plans" / "b.md").write_text(
        "---\nid: same-id\ntype: plan\ntitle: B\nstatus: active\ngoal: missing-goal\n---\n",
        encoding="utf-8",
    )
    first = build_copilot_index(vault).to_dict()
    second = build_copilot_index(vault).to_dict()
    assert first == second
    codes = [item["code"] for item in first["diagnostics"]]
    assert codes.count("copilot-id-duplicate") == 2
    assert "unknown-plan-reference" in codes
    assert "unknown-goal-reference" in codes


def test_schema_compatibility_is_conservative() -> None:
    legacy = compatibility_diagnostics(schema_version=0, path="goals/a.md")
    future = compatibility_diagnostics(schema_version=99, path="goals/a.md")
    assert legacy[0].code == "schema-version-legacy"
    assert future[0].code == "schema-version-unsupported"


def test_bridge_and_python_contract_match(tmp_path: Path) -> None:
    (tmp_path / "goals").mkdir()
    (tmp_path / "goals" / "a.md").write_text(
        "---\nid: goal-a\ntype: goal\ntitle: A\nstatus: active\n---\n",
        encoding="utf-8",
    )
    direct = inspect_copilot_note(tmp_path, "goals/a.md")
    app = BridgeApplication(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        actor_id="tester",
    )
    assert app.dispatch("copilot.note.inspect", {"path": "goals/a.md"}) == direct


def test_typescript_contract_has_no_provider_specific_fields() -> None:
    content = Path("packages/obsidian-plugin/src/goal-plan.ts").read_text(encoding="utf-8").lower()
    assert "anthropic" not in content
    assert "claude" not in content
    assert "openai" not in content
