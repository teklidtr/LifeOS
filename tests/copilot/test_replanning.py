from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.attention import evaluate_attention
from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    Milestone,
    PlanAssumption,
    PlanOption,
    ReplanningError,
    ReplanningProposalRequest,
    ReviewEvidence,
    build_replanning_review,
    create_replanning_proposal,
    scan_replanning_triggers,
    suppress_replanning_suggestion,
)
from lifeos.daily import DailyInteractionService, TaskOutcomeRequest, content_hash
from lifeos.desktop import DesktopProposalService
from lifeos.markdown.parser import parse_markdown_note
from lifeos.reviews import build_review_workflow


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


def _ownership(vault: Path) -> None:
    _write(
        vault / "system" / "generated-ownership.json",
        '{"schema_version": 1, "owned_files": {}}\n',
    )


def _goal(vault: Path, *, with_plan: bool = False) -> Path:
    active = "[plan-cell]" if with_plan else "[]"
    path = vault / "goals" / "cell.md"
    _write(
        path,
        f"""---
copilot_schema_version: 1
id: goal-cell
type: goal
title: Learn cell biology
status: active
horizon: year
why: Understand living systems.
desired_change: Explain six chapters.
constraints: [Four hours weekly]
active_plans: {active}
---

The original direction remains visible.
""",
    )
    return path


def _plan(vault: Path, *, task_status: str = "todo", blocked: bool = False) -> Path:
    blockers = "[task-prerequisite]" if blocked else "[]"
    path = vault / "plans" / "cell.md"
    _write(
        path,
        f"""---
copilot_schema_version: 1
id: plan-cell
type: plan
title: Cell foundations
status: active
goal: goal-cell
desired_outcome: Explain chapters one through three.
success_evidence: [Three synthesis notes]
boundaries: [No complete textbook backlog]
assumptions: [Four hours weekly remains available]
review_date: 2026-07-20
rolling_wave_depth: 2
milestones:
  - milestone_id: milestone-cell-1
    title: Build foundations
    outcome: Explain membrane basics.
    status: completed
    wave: current
  - milestone_id: milestone-cell-2
    title: Integrate mechanisms
    outcome: Explain transport and signaling.
    status: planned
    wave: next
tasks:
  - task_id: task-cell-read-1
    title: Read and annotate chapter one
    status: {task_status}
    duration: 60
    energy: medium
    motivation: medium
    mode: study
    milestone_id: milestone-cell-2
    blocked_by: {blockers}
    source_refs: [goal-cell]
---


The original plan narrative remains visible.  
\tTail""",
    )
    return path


def _codes(vault: Path, runtime: Path, day: date = date(2026, 7, 16)) -> set[str]:
    return {
        item.code
        for item in scan_replanning_triggers(vault_root=vault, runtime_dir=runtime, as_of=day)
    }


def test_goal_without_active_plan_and_plan_without_next_action(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path)
    assert "goal-no-active-plan" in _codes(tmp_path, runtime)

    _goal(tmp_path, with_plan=True)
    _plan(tmp_path, blocked=True)
    codes = _codes(tmp_path, runtime)
    assert "goal-no-active-plan" not in codes
    assert "plan-no-feasible-next-action" in codes


def test_completed_milestone_review_date_and_next_wave_are_visible(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path, with_plan=True)
    _plan(tmp_path)
    triggers = scan_replanning_triggers(
        vault_root=tmp_path, runtime_dir=runtime, as_of=date(2026, 7, 16)
    )
    by_code = {item.code: item for item in triggers}
    assert "milestone-completed" in by_code
    assert "review-date-approaching" in by_code
    assert "adjust-next-wave" in by_code["milestone-completed"].possible_outcomes


def test_review_compares_original_current_and_changed_conditions(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path, with_plan=True)
    plan = _plan(tmp_path)
    original = PlanOption(
        schema_version=1,
        option_id="option-cell-original",
        title="Original cell option",
        strategy="Study one bounded wave",
        desired_outcome="Explain chapters one and two.",
        boundaries=("No complete textbook backlog",),
        assumptions=(
            PlanAssumption(
                "assumption-time", "Four hours remain available", "user", "goal-cell", "medium"
            ),
        ),
        success_evidence=("Two synthesis notes",),
        risks=("Pacing risk",),
        review_date=date(2026, 8, 1),
        milestones=(
            Milestone(
                "milestone-original", "Foundation", "Explain chapters one and two", wave="current"
            ),
        ),
        tradeoffs=("Less breadth",),
        unresolved_questions=(),
        source_refs=("goals/cell.md",),
    )
    evidence = (
        ReviewEvidence(
            "correction-deadline",
            "correction",
            "The deadline moved to September.",
            "review/weekly.md",
            date(2026, 7, 16),
        ),
        ReviewEvidence(
            "answer-capacity",
            "review-answer",
            "Available capacity fell to two hours weekly.",
            "reviews/week.md",
            date(2026, 7, 16),
        ),
        ReviewEvidence(
            "answer-scope",
            "review-answer",
            "Scope now excludes chapter three.",
            None,
            date(2026, 7, 16),
        ),
        ReviewEvidence(
            "answer-prerequisite",
            "review-answer",
            "A prerequisite course now blocks signaling.",
            None,
            date(2026, 7, 16),
        ),
    )
    review = build_replanning_review(
        vault_root=tmp_path,
        runtime_dir=runtime,
        target_path="plans/cell.md",
        as_of=date(2026, 7, 16),
        original_option=original,
        corrections=evidence[:1],
        recent_answers=evidence[1:],
        expected_hash="sha256:" + content_hash(plan.read_text()),
    )
    assert {item.dimension for item in review.comparisons} >= {
        "desired outcome",
        "scope boundaries",
        "review date",
        "execution evidence",
    }
    changed = next(item for item in review.triggers if item.code == "constraints-changed")
    assert all(word in changed.detail for word in ("deadline", "scope", "capacity", "prerequisite"))
    assert "revise-scope" in review.recommended_outcomes
    assert review.original_option_id == "option-cell-original"


def test_repeated_avoidance_preserves_competing_explanations(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path, with_plan=True)
    plan = _plan(tmp_path)
    service = DailyInteractionService(vault_root=tmp_path, runtime_dir=runtime)
    original_body = _body_bytes(plan)
    for event_id, reason, day in (
        ("event-scope", "scope", date(2026, 7, 14)),
        ("event-energy", "energy", date(2026, 7, 15)),
    ):
        service.record_task_outcome(
            TaskOutcomeRequest(
                event_id,
                "plans/cell.md",
                "task-cell-read-1",
                "partial",
                day,
                content_hash(plan.read_bytes()),
                actual_minutes=10,
                reason=reason,
            )
        )
    assert _body_bytes(plan) == original_body
    trigger = next(
        item
        for item in scan_replanning_triggers(
            vault_root=tmp_path, runtime_dir=runtime, as_of=date(2026, 7, 16)
        )
        if item.code == "repeated-avoidance"
    )
    assert "energy" in trigger.detail and "scope" in trigger.detail
    assert "reopen-clarification" in trigger.possible_outcomes


def test_continue_unchanged_pause_supersede_close_and_reopen_paths(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _ownership(tmp_path)
    _goal(tmp_path, with_plan=True)
    plan = _plan(tmp_path)
    original_body = _body_bytes(plan)
    review = build_replanning_review(
        vault_root=tmp_path,
        runtime_dir=runtime,
        target_path="plans/cell.md",
        as_of=date(2026, 7, 16),
    )
    common = dict(
        review_id=review.review_id,
        target_path="plans/cell.md",
        expected_hash=review.target_hash,
        rationale="Reality changed, so preserve intent and review the next decision explicitly.",
        evidence_fingerprint=review.triggers[0].evidence_fingerprint,
    )
    assert (
        create_replanning_proposal(
            vault_root=tmp_path,
            request=ReplanningProposalRequest(outcome="continue-unchanged", changes={}, **common),
            actor_id="tester",
        )
        is None
    )

    pause = create_replanning_proposal(
        vault_root=tmp_path,
        request=ReplanningProposalRequest(outcome="pause", changes={}, **common),
        actor_id="tester",
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert pause is not None
    assert plan.read_text(encoding="utf-8").find("status: active") >= 0
    desktop = DesktopProposalService(vault_root=tmp_path, actor_id="tester")
    for action in ("submit", "approve", "apply"):
        challenge = desktop.prepare(proposal_id=pause.proposal_id, action=action)
        desktop.execute(proposal_id=pause.proposal_id, action=action, token=challenge.token)
    paused = plan.read_text(encoding="utf-8")
    assert "status: paused" in paused
    assert "decision_lineage:" in paused
    assert _body_bytes(plan) == original_body

    # Each additional outcome is created from fresh canonical state and remains proposal-only.
    for index, (outcome, changes) in enumerate(
        (
            ("supersede", {"superseded_by": "plan-cell-v2"}),
            ("close", {}),
            ("reopen-clarification", {}),
        ),
        start=1,
    ):
        current = build_replanning_review(
            vault_root=tmp_path,
            runtime_dir=runtime,
            target_path="plans/cell.md",
            as_of=date(2026, 7, 16),
        )
        result = create_replanning_proposal(
            vault_root=tmp_path,
            request=ReplanningProposalRequest(
                review_id=current.review_id,
                target_path=current.target_path,
                expected_hash=current.target_hash,
                outcome=outcome,
                rationale=f"Visible review choice {index}.",
                evidence_fingerprint=f"sha256:{index:064x}",
                changes=changes,
            ),
            actor_id="tester",
            now=datetime(2026, 7, 16, 0, 0, index, tzinfo=timezone.utc),
        )
        assert result is not None
        assert desktop.inspect(result.proposal_id).status == "draft"
        assert plan.read_text(encoding="utf-8") == paused


def test_rejected_suggestion_is_suppressed_until_evidence_changes(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    goal = _goal(tmp_path)
    trigger = next(
        iter(
            scan_replanning_triggers(
                vault_root=tmp_path, runtime_dir=runtime, as_of=date(2026, 7, 16)
            )
        )
    )
    suppress_replanning_suggestion(
        runtime_dir=runtime,
        trigger_id=trigger.trigger_id,
        evidence_fingerprint=trigger.evidence_fingerprint,
    )
    assert (
        scan_replanning_triggers(vault_root=tmp_path, runtime_dir=runtime, as_of=date(2026, 7, 16))
        == ()
    )
    goal.write_text(goal.read_text(encoding="utf-8") + "New explicit evidence.\n", encoding="utf-8")
    changed = scan_replanning_triggers(
        vault_root=tmp_path, runtime_dir=runtime, as_of=date(2026, 7, 16)
    )
    assert changed and changed[0].trigger_id == trigger.trigger_id
    assert changed[0].evidence_fingerprint != trigger.evidence_fingerprint


def test_stale_source_fails_closed_in_review_and_proposal(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path, with_plan=True)
    plan = _plan(tmp_path)
    old_hash = "sha256:" + content_hash(plan.read_bytes())
    plan.write_text(plan.read_text() + "Concurrent canonical edit.\n", encoding="utf-8")
    concurrent = plan.read_bytes()
    with pytest.raises(ReplanningError, match="changed during replanning review"):
        build_replanning_review(
            vault_root=tmp_path,
            runtime_dir=runtime,
            target_path="plans/cell.md",
            as_of=date(2026, 7, 16),
            expected_hash=old_hash,
        )
    assert plan.read_bytes() == concurrent
    current = build_replanning_review(
        vault_root=tmp_path,
        runtime_dir=runtime,
        target_path="plans/cell.md",
        as_of=date(2026, 7, 16),
    )
    plan.write_text(plan.read_text() + "Another edit.\n", encoding="utf-8")
    another = plan.read_bytes()
    with pytest.raises(ReplanningError, match="changed after review"):
        create_replanning_proposal(
            vault_root=tmp_path,
            request=ReplanningProposalRequest(
                current.review_id,
                current.target_path,
                current.target_hash,
                "pause",
                "Pause after review.",
                "sha256:" + "a" * 64,
                {},
            ),
            actor_id="tester",
        )
    assert plan.read_bytes() == another


def test_daily_attention_weekly_review_and_bridge_integration(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _goal(tmp_path)
    attention = evaluate_attention(
        vault_root=tmp_path,
        runtime_dir=runtime,
        as_of=datetime(2026, 7, 16, 10, tzinfo=timezone.utc),
    )
    replanning = next(item for item in attention.items if item.kind == "replanning_review")
    assert any(action.action == "replan" for action in replanning.actions)
    weekly = build_review_workflow(
        vault_root=tmp_path, runtime_dir=runtime, kind="weekly", day=date(2026, 7, 16)
    )
    section = next(item for item in weekly.sections if item.section_id == "goal-plan-reviews")
    assert section.items and section.items[0].action == "replan"

    app = BridgeApplication(vault_root=tmp_path, runtime_dir=runtime, actor_id="tester")
    scanned = app.dispatch("copilot.replanning.scan", {"as_of": "2026-07-16"})
    assert scanned[0]["code"] == "goal-no-active-plan"
    review = app.dispatch(
        "copilot.replanning.review",
        {
            "target_path": "goals/cell.md",
            "as_of": "2026-07-16",
            "corrections": [
                {
                    "evidence_id": "correction-capacity",
                    "kind": "correction",
                    "statement": "Capacity changed.",
                }
            ],
        },
    )
    unchanged = app.dispatch(
        "copilot.replanning.proposal.create",
        {
            "review_id": review["review_id"],
            "target_path": review["target_path"],
            "expected_hash": review["target_hash"],
            "outcome": "continue-unchanged",
            "rationale": "The direction still fits.",
            "evidence_fingerprint": review["triggers"][0]["evidence_fingerprint"],
            "changes": {},
        },
    )
    assert unchanged == {"proposal_created": False, "outcome": "continue-unchanged"}
