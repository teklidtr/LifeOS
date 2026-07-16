from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.copilot import (
    CopilotProposalError, CopilotProposalRequest, ConflictPlanEdit,
    PlanningSessionService, build_copilot_index, build_planning_context,
    create_copilot_plan_proposal, decompose_plan_option, generate_plan_options,
)
from lifeos.desktop import DesktopProposalService
from lifeos.proposals.loader import load_proposal_directory


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _goal(vault: Path) -> None:
    _write(vault / "goals" / "cell.md", "---\ncopilot_schema_version: 1\nid: goal-cell\ntype: goal\ntitle: Learn cells\nstatus: active\nhorizon: year\nwhy: Understand cells.\ndesired_change: Explain six chapters.\nconstraints: [Four hours weekly]\nactive_plans: []\n---\n\nHuman goal notes stay here.\n")
    _write(vault / "system" / "generated-ownership.json", '{"schema_version": 1, "owned_files": {}}\n')
    (vault / "plans").mkdir(parents=True, exist_ok=True)


def _conflict(vault: Path) -> None:
    _write(vault / "plans" / "old.md", "---\ncopilot_schema_version: 1\nid: plan-old\ntype: plan\ntitle: Old cell plan\nstatus: active\ngoal: goal-other\ndesired_outcome: Explain six chapters.\ntasks: []\n---\n\nHuman conflict notes stay here.\n")


def _draft(vault: Path):
    index = build_copilot_index(vault)
    goal = index.goals[0]
    sessions = PlanningSessionService(vault_root=vault, runtime_dir=vault / ".lifeos")
    snapshot = sessions.start(goal_path=goal.path, session_id="session-cell")
    context = build_planning_context(vault_root=vault, goal=goal, index=index)
    options = generate_plan_options(goal=goal, session=snapshot.envelope.session, readiness=snapshot.envelope.readiness, context=context, index=index, as_of=date(2026, 7, 16))
    option = options.options[0]
    decomposition = decompose_plan_option(option=option, horizon=goal.horizon)
    return goal, sessions, snapshot, option, decomposition, index


def _request(goal, snapshot, option, decomposition, **changes):
    values = dict(
        session_id="session-cell", expected_session_revision=snapshot.envelope.session.source_revision,
        goal_path=goal.path, expected_goal_hash=goal.content_hash,
        plan_id="plan-cell-new", plan_path="plans/cell-new.md", plan_title="Edited cell plan",
        desired_outcome="Explain the first six chapters with concise notes",
        included_milestone_ids=tuple(item.milestone_id for item in option.milestones),
        included_action_ids=tuple(item.action.task_id for item in decomposition.actions),
        milestone_edits={}, action_edits={}, goal_updates={"review_cadence": "monthly"}, link_goal=True,
    )
    values.update(changes)
    return CopilotProposalRequest(**values)


def test_new_plan_goal_link_item_edits_and_exclusion_are_proposal_only(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, sessions, snapshot, option, decomposition, index = _draft(tmp_path)
    action_id = decomposition.actions[0].action.task_id
    milestone_id = option.milestones[0].milestone_id
    request = _request(goal, snapshot, option, decomposition, milestone_edits={milestone_id: {"title": "Edited milestone"}}, action_edits={action_id: {"duration": 45, "title": "Edited next action"}})
    result = create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=index, request=request, actor_id="tester", session_service=sessions, now=datetime(2026, 7, 16, tzinfo=timezone.utc))
    assert not (tmp_path / "plans" / "cell-new.md").exists()
    assert "plan-cell-new" not in (tmp_path / "goals" / "cell.md").read_text()
    loaded = load_proposal_directory(tmp_path / result.proposal_path, proposals_root=tmp_path / "proposals")
    assert loaded.proposal is not None
    ops = loaded.proposal.patch_document.operations
    assert [item.op for item in ops][:2] == ["create_file", "patch_human_file"]
    assert "Edited next action" in ops[0].new_content
    session = sessions.get("session-cell").envelope.session
    assert session.status == "proposal-created" and result.proposal_id in session.proposal_ids


def test_selected_exclusion_and_unrelated_goal_body_are_preserved_after_apply(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, sessions, snapshot, option, decomposition, index = _draft(tmp_path)
    request = _request(goal, snapshot, option, decomposition, included_action_ids=())
    result = create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=index, request=request, actor_id="tester", session_service=sessions, now=datetime(2026, 7, 16, 0, 0, 1, tzinfo=timezone.utc))
    desktop = DesktopProposalService(vault_root=tmp_path, actor_id="tester")
    for action in ("submit", "approve", "apply"):
        challenge = desktop.prepare(proposal_id=result.proposal_id, action=action)
        desktop.execute(proposal_id=result.proposal_id, action=action, token=challenge.token)
    plan = (tmp_path / "plans" / "cell-new.md").read_text()
    goal_text = (tmp_path / "goals" / "cell.md").read_text()
    assert "tasks: []" in plan
    assert "plan-cell-new" in goal_text
    assert "Human goal notes stay here." in goal_text
    assert build_copilot_index(tmp_path).plans[0].plan_id == "plan-cell-new"


def test_explicit_supersession_uses_exact_hash_and_preserves_human_body(tmp_path: Path) -> None:
    _goal(tmp_path); _conflict(tmp_path)
    goal, sessions, snapshot, option, decomposition, index = _draft(tmp_path)
    request = _request(goal, snapshot, option, decomposition, conflict_edits=(ConflictPlanEdit("plans/old.md", "supersede"),))
    result = create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=index, request=request, actor_id="tester", session_service=sessions, now=datetime(2026, 7, 16, 0, 0, 2, tzinfo=timezone.utc))
    assert dict(result.base_hashes)["plans/old.md"].startswith("sha256:")
    loaded = load_proposal_directory(tmp_path / result.proposal_path, proposals_root=tmp_path / "proposals")
    assert loaded.proposal is not None
    assert any(op.target_path == "plans/old.md" for op in loaded.proposal.patch_document.operations)


def test_duplicate_ids_invalid_links_and_stale_goal_fail_closed(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, sessions, snapshot, option, decomposition, index = _draft(tmp_path)
    _write(tmp_path / "plans" / "duplicate.md", "---\ncopilot_schema_version: 1\nid: plan-cell-new\ntype: plan\ntitle: Existing\nstatus: active\ntasks: []\n---\n")
    with pytest.raises(CopilotProposalError, match="duplicate plan id"):
        create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=build_copilot_index(tmp_path), request=_request(goal, snapshot, option, decomposition), actor_id="tester")
    (tmp_path / "plans" / "duplicate.md").unlink()
    (tmp_path / "goals" / "cell.md").write_text((tmp_path / "goals" / "cell.md").read_text() + "Concurrent edit\n")
    with pytest.raises(CopilotProposalError, match="goal changed"):
        create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=index, request=_request(goal, snapshot, option, decomposition), actor_id="tester")


def test_rejected_lifecycle_leaves_canonical_files_unchanged(tmp_path: Path) -> None:
    _goal(tmp_path)
    goal, sessions, snapshot, option, decomposition, index = _draft(tmp_path)
    result = create_copilot_plan_proposal(vault_root=tmp_path, option=option, decomposition=decomposition, index=index, request=_request(goal, snapshot, option, decomposition), actor_id="tester", session_service=sessions, now=datetime(2026, 7, 16, 0, 0, 3, tzinfo=timezone.utc))
    desktop = DesktopProposalService(vault_root=tmp_path, actor_id="tester")
    challenge = desktop.prepare(proposal_id=result.proposal_id, action="submit")
    desktop.execute(proposal_id=result.proposal_id, action="submit", token=challenge.token)
    challenge = desktop.prepare(proposal_id=result.proposal_id, action="reject")
    desktop.execute(proposal_id=result.proposal_id, action="reject", token=challenge.token, reason="Not now")
    assert not (tmp_path / "plans" / "cell-new.md").exists()
    assert desktop.inspect(result.proposal_id).status == "rejected"


def test_bridge_creates_reviewable_proposal_without_applying(tmp_path: Path) -> None:
    from lifeos.bridge import BridgeApplication

    _goal(tmp_path)
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="tester")
    session = app.dispatch("copilot.session.start", {"goal_path": "goals/cell.md", "session_id": "session-cell"})
    options = app.dispatch("copilot.options.generate", {"session_id": "session-cell", "as_of": "2026-07-16"})
    option = options["options"][0]
    decomposition = app.dispatch("copilot.option.decompose", {"session_id": "session-cell", "option_id": option["option_id"], "as_of": "2026-07-16"})
    result = app.dispatch("copilot.proposal.create", {
        "session_id": "session-cell", "option_id": option["option_id"], "as_of": "2026-07-16",
        "expected_revision": session["session"]["source_revision"],
        "plan_id": "plan-cell-bridge", "plan_path": "plans/cell-bridge.md",
        "plan_title": "Bridge cell plan", "desired_outcome": "Explain six chapters",
        "included_milestone_ids": [item["milestone_id"] for item in option["milestones"]],
        "included_action_ids": [item["task_id"] for item in decomposition["actions"]],
    })
    assert (tmp_path / result["proposal_path"] / "patches.json").exists()
    assert not (tmp_path / "plans" / "cell-bridge.md").exists()
