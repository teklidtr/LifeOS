from __future__ import annotations

from pathlib import Path

import pytest

from lifeos.bridge import BridgeApplication
from lifeos.copilot import build_copilot_index
from lifeos.copilot.context import (
    PlanningContextError,
    PlanningContextPolicy,
    build_planning_context,
)
from lifeos.copilot.readiness import evaluate_goal_readiness


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ready_goal(path: Path, *, active_plans: str = "[]") -> None:
    _write(
        path,
        "---\n"
        "copilot_schema_version: 1\n"
        "id: goal-write-book\n"
        "type: goal\n"
        "title: Write a small book\n"
        "status: active\n"
        "horizon: year\n"
        "why: Preserve and share a useful argument.\n"
        "desired_change: Complete a coherent first manuscript.\n"
        "constraints: [Keep weekends partly free]\n"
        f"active_plans: {active_plans}\n"
        "---\n"
        "The book should remain enjoyable rather than consume every hobby.\n",
    )


def test_readiness_distinguishes_ready_incomplete_archived_and_covered(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md")
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    report = evaluate_goal_readiness(goal, index=index)
    assert report.ready is True
    assert report.path == "plan"

    _write(
        tmp_path / "goals" / "incomplete.md",
        "---\nid: goal-incomplete\ntype: goal\ntitle: Maybe learn pottery\nstatus: active\n---\n",
    )
    incomplete_index = build_copilot_index(tmp_path)
    incomplete = next(item for item in incomplete_index.goals if item.goal_id == "goal-incomplete")
    incomplete_report = evaluate_goal_readiness(incomplete, index=incomplete_index)
    assert incomplete_report.path == "clarify"
    assert set(incomplete_report.missing_fields) == {"why", "desired_change", "horizon"}

    _write(
        tmp_path / "goals" / "archived.md",
        "---\nid: goal-archived\ntype: goal\ntitle: Old direction\nstatus: archived\n---\n",
    )
    archived_index = build_copilot_index(tmp_path)
    archived = next(item for item in archived_index.goals if item.goal_id == "goal-archived")
    assert evaluate_goal_readiness(archived, index=archived_index).path == "decline"

    _write(
        tmp_path / "plans" / "book.md",
        "---\nid: plan-book\ntype: plan\ntitle: Book manuscript\nstatus: active\ngoal: goal-write-book\n---\n",
    )
    _ready_goal(tmp_path / "goals" / "ready.md", active_plans="[plan-book]")
    covered_index = build_copilot_index(tmp_path)
    covered = next(item for item in covered_index.goals if item.goal_id == "goal-write-book")
    assert evaluate_goal_readiness(covered, index=covered_index).path == "link-existing-plan"


def test_context_is_bounded_traceable_redacted_and_stable(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md")
    _write(
        tmp_path / "wiki" / "support.md",
        "---\nid: source-support\ntitle: Supporting note\n---\nSecretName " + "useful detail " * 100,
    )
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    pack = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("wiki/support.md",),
        redact_terms=("SecretName",),
        max_total_bytes=500,
        max_item_bytes=300,
    )
    assert [item.path for item in pack.items] == ["goals/ready.md", "wiki/support.md"]
    assert pack.items[1].source_id == "source-support"
    assert "SecretName" not in pack.items[1].excerpt
    assert pack.items[1].redactions[0].occurrences == 1
    assert pack.truncated is True
    assert pack.to_dict() == build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("wiki/support.md",),
        redact_terms=("SecretName",),
        max_total_bytes=500,
        max_item_bytes=300,
    ).to_dict()


def test_sensitive_scope_requires_policy_and_explicit_user_action(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md")
    _write(tmp_path / "journal" / "private.md", "---\nid: private-note\n---\nPrivate facts")
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    denied = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("journal/private.md",),
    )
    assert "journal/private.md" not in {item.path for item in denied.items}
    assert any(item.reason == "sensitive-scope-denied" for item in denied.omissions)

    allowed = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("journal/private.md",),
        policy=PlanningContextPolicy(allowed_sensitive_roots=("journal",)),
    )
    assert "journal/private.md" in {item.path for item in allowed.items}


def test_context_reports_stale_deleted_excluded_and_budget_omissions(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md", active_plans="[plan-one]")
    _write(
        tmp_path / "plans" / "one.md",
        "---\nid: plan-one\ntype: plan\ntitle: Existing\nstatus: active\ngoal: goal-write-book\n---\n",
    )
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    pack = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("wiki/missing.md",),
        exclude_paths=("plans/one.md",),
        expected_hashes={"goals/ready.md": "sha256:old"},
        max_total_bytes=100,
        max_item_bytes=100,
    )
    assert pack.items[0].freshness == "stale"
    reasons = {item.reason for item in pack.omissions}
    assert "explicitly-excluded" in reasons
    assert "source-unavailable" in reasons


def test_context_rejects_unsafe_or_conflicting_controls(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md")
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    with pytest.raises(PlanningContextError, match="unsafe"):
        build_planning_context(
            vault_root=tmp_path, goal=goal, index=index, include_paths=("../secret.md",)
        )
    with pytest.raises(PlanningContextError, match="both"):
        build_planning_context(
            vault_root=tmp_path,
            goal=goal,
            index=index,
            include_paths=("wiki/a.md",),
            exclude_paths=("wiki/a.md",),
        )


def test_bridge_exposes_readiness_and_context_preview(tmp_path: Path) -> None:
    _ready_goal(tmp_path / "goals" / "ready.md")
    app = BridgeApplication(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        actor_id="tester",
    )
    readiness = app.dispatch("copilot.goal.readiness", {"goal_path": "goals/ready.md"})
    preview = app.dispatch("copilot.context.preview", {"goal_path": "goals/ready.md"})
    assert readiness["path"] == "plan"
    assert preview["items"][0]["path"] == "goals/ready.md"
    assert preview["lexical_only"] is True
