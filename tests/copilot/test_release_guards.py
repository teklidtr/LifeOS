from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from lifeos.bridge.protocol import CAPABILITIES, PROTOCOL_VERSION
from lifeos.copilot import (
    CURRENT_COPILOT_SCHEMA_VERSION,
    PlanningSessionService,
    build_copilot_index,
    build_planning_context,
    compatibility_diagnostics,
    parse_goal_note,
    parse_plan_note,
)
from lifeos.versioning import DESKTOP_RUNTIME_SCHEMA_VERSION


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _goal(i: int) -> str:
    return f"---\ncopilot_schema_version: 1\nid: goal-{i}\ntype: goal\ntitle: Goal {i}\nstatus: active\nhorizon: year\nwhy: Direction {i}.\ndesired_change: Visible outcome {i}.\nconstraints: [Bounded capacity]\n---\n"


def _plan(i: int) -> str:
    return f"---\ncopilot_schema_version: 1\nid: plan-{i}\ntype: plan\ntitle: Plan {i}\nstatus: archived\ngoal: goal-{i}\ndesired_outcome: Visible outcome {i}.\ntasks: []\n---\n"


def test_schema_protocol_plugin_and_provider_neutral_contracts_align() -> None:
    assert CURRENT_COPILOT_SCHEMA_VERSION == 1
    assert DESKTOP_RUNTIME_SCHEMA_VERSION == 1
    assert PROTOCOL_VERSION.startswith("1.")
    assert {
        "copilot.context.preview",
        "copilot.session.start",
        "copilot.options.generate",
        "copilot.option.decompose",
        "copilot.capacity.check",
        "copilot.explain",
        "copilot.proposal.create",
        "copilot.replanning.review",
        "copilot.replanning.proposal.create",
    } <= set(CAPABILITIES)
    ts = Path("packages/obsidian-plugin/src/goal-plan.ts").read_text(encoding="utf-8").casefold()
    workspace = Path("packages/obsidian-plugin/src/goal-plan-workspace.ts").read_text(encoding="utf-8").casefold()
    repository_contract = ts + workspace
    for provider in ("claude", "anthropic", "openai", "gemini"):
        assert provider not in repository_contract
    assert compatibility_diagnostics(schema_version=99, path="goals/future.md")[0].severity == "error"


def test_large_vault_index_and_context_stay_within_release_budgets(tmp_path: Path) -> None:
    for i in range(350):
        _write(tmp_path / "goals" / f"goal-{i}.md", _goal(i))
        _write(tmp_path / "plans" / f"plan-{i}.md", _plan(i))
    _write(
        tmp_path / "wiki" / "focus.md",
        "---\nid: wiki-focus\ntype: wiki\ntitle: Focus\n---\n\n" + "bounded evidence " * 1200,
    )
    started = time.perf_counter()
    index = build_copilot_index(tmp_path)
    index_elapsed = time.perf_counter() - started
    assert len(index.goals) == 350 and len(index.plans) == 350
    assert index_elapsed < 5.0

    goal = index.goals[0]
    started = time.perf_counter()
    context = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("wiki/focus.md",),
        max_total_bytes=24_000,
        max_item_bytes=6_000,
    )
    context_elapsed = time.perf_counter() - started
    assert context.total_bytes <= 24_000
    assert all(item.included_bytes <= 6_000 for item in context.items)
    assert context_elapsed < 3.0


def test_removing_disposable_copilot_state_preserves_canonical_markdown(tmp_path: Path) -> None:
    goal_path = tmp_path / "goals" / "cell.md"
    plan_path = tmp_path / "plans" / "cell.md"
    _write(goal_path, _goal(1).replace("goal-1", "goal-cell").replace("Goal 1", "Learn cells"))
    _write(
        plan_path,
        _plan(1).replace("plan-1", "plan-cell").replace("goal-1", "goal-cell").replace("Plan 1", "Cell plan")
        .replace("tasks: []", "decision_lineage:\n  - decision_id: decision-visible\n    outcome: continue-unchanged\n    rationale: Still fits\ntasks: []"),
    )
    _write(tmp_path / "proposals" / "prop-example" / "proposal.md", "---\nid: prop-example\ntitle: Example\nstatus: rejected\n---\n")
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    service.start(goal_path="goals/cell.md", session_id="session-removal")
    before_goal = goal_path.read_bytes()
    before_plan = plan_path.read_bytes()
    before_proposal = (tmp_path / "proposals" / "prop-example" / "proposal.md").read_bytes()

    shutil.rmtree(tmp_path / ".lifeos")
    assert goal_path.read_bytes() == before_goal
    assert plan_path.read_bytes() == before_plan
    assert (tmp_path / "proposals" / "prop-example" / "proposal.md").read_bytes() == before_proposal
    assert parse_goal_note(path="goals/cell.md", content=goal_path.read_text()).goal_id == "goal-cell"
    assert parse_plan_note(path="plans/cell.md", content=plan_path.read_text()).plan_id == "plan-cell"
    rebuilt = build_copilot_index(tmp_path)
    assert rebuilt.goals[0].goal_id == "goal-cell" and rebuilt.plans[0].plan_id == "plan-cell"
    assert "decision-visible" in plan_path.read_text(encoding="utf-8")


def test_no_claude_workspace_files_are_tracked() -> None:
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    assert ".claude/" in ignored and "CLAUDE.md" in ignored
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    assert not any(path == "CLAUDE.md" or path.startswith(".claude/") for path in tracked)
