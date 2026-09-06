from __future__ import annotations

from datetime import date
from pathlib import Path

from lifeos.bridge import BridgeApplication
from lifeos.copilot import (
    PlanOptionError,
    PlanningSessionService,
    build_copilot_index,
    build_planning_context,
    generate_plan_options,
)
from lifeos.desktop import DesktopProposalService

import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ready_vault(vault: Path) -> None:
    _write(
        vault / "goals" / "cell.md",
        """---
copilot_schema_version: 1
id: goal-cell
type: goal
title: Learn cell biology
status: active
horizon: year
why: Understand living systems.
desired_change: Explain the first six chapters clearly.
constraints: [Four hours weekly, Protect running and rest]
non_goals: [Do not create one task per flashcard]
active_plans: []
---

This direction stays human-readable without the copilot.
""",
    )
    _write(
        vault / "wiki" / "cell-reading.md",
        "---\nid: wiki-cell-reading\ntype: wiki\ntitle: Cell reading notes\n---\n\nUse synthesis notes, not completion theater.\n",
    )
    _write(
        vault / "journal" / "private.md",
        "---\nid: journal-private\ntype: journal\ntitle: Private reflection\n---\n\nSensitive reflection that must be denied by default.\n",
    )
    _write(
        vault / "system" / "generated-ownership.json",
        '{"schema_version": 1, "owned_files": {}}\n',
    )
    (vault / "plans").mkdir(parents=True, exist_ok=True)


def test_full_goal_to_applied_plan_and_later_replanning(tmp_path: Path) -> None:
    _ready_vault(tmp_path)
    runtime = tmp_path / ".lifeos"
    app = BridgeApplication(vault_root=tmp_path, runtime_dir=runtime, actor_id="tester")

    preview = app.dispatch(
        "copilot.context.preview",
        {
            "goal_path": "goals/cell.md",
            "include_paths": ["wiki/cell-reading.md", "journal/private.md"],
            "redact_terms": ["completion theater"],
        },
    )
    assert preview["items"]
    assert any(item["redactions"] for item in preview["items"])
    assert any(
        item["path"] == "journal/private.md" and item["reason"] == "sensitive-scope-denied"
        for item in preview["omissions"]
    )

    session = app.dispatch(
        "copilot.session.start",
        {
            "goal_path": "goals/cell.md",
            "session_id": "session-cell-e2e",
            "selected_context_refs": ["wiki/cell-reading.md"],
        },
    )
    options = app.dispatch(
        "copilot.options.generate",
        {
            "session_id": "session-cell-e2e",
            "as_of": "2026-07-16",
        },
    )
    option = options["options"][0]
    decomposition = app.dispatch(
        "copilot.option.decompose",
        {
            "session_id": "session-cell-e2e",
            "option_id": option["option_id"],
            "as_of": "2026-07-16",
        },
    )
    capacity = app.dispatch(
        "copilot.capacity.check",
        {
            "session_id": "session-cell-e2e",
            "option_id": option["option_id"],
            "as_of": "2026-07-16",
            "available_minutes": 240,
            "recurring_workloads": [
                {
                    "workload_id": "running",
                    "title": "Running",
                    "minutes": 60,
                    "kind": "exercise",
                    "protected": True,
                },
                {
                    "workload_id": "rest",
                    "title": "Unstructured rest",
                    "minutes": 60,
                    "kind": "rest",
                    "protected": True,
                },
            ],
            "adaptive_durations": {item["task_id"]: 75 for item in decomposition["actions"]},
        },
    )
    assert capacity["baseline"]["label"] == "baseline"
    assert capacity["adaptive"]["label"] == "adaptive"
    overloaded = app.dispatch(
        "copilot.capacity.check",
        {
            "session_id": "session-cell-e2e",
            "option_id": option["option_id"],
            "as_of": "2026-07-16",
            "available_minutes": 90,
            "recurring_workloads": [
                {
                    "workload_id": "running",
                    "title": "Running",
                    "minutes": 60,
                    "kind": "exercise",
                    "protected": True,
                },
                {
                    "workload_id": "rest",
                    "title": "Unstructured rest",
                    "minutes": 60,
                    "kind": "rest",
                    "protected": True,
                },
            ],
        },
    )
    assert overloaded["baseline"]["fit"] == "overload"
    explanation = app.dispatch(
        "copilot.explain",
        {
            "session_id": "session-cell-e2e",
            "option_id": option["option_id"],
            "as_of": "2026-07-16",
            "available_minutes": 240,
        },
    )
    assert explanation["option_id"] == option["option_id"]

    proposal = app.dispatch(
        "copilot.proposal.create",
        {
            "session_id": "session-cell-e2e",
            "option_id": option["option_id"],
            "as_of": "2026-07-16",
            "expected_revision": session["session"]["source_revision"],
            "plan_id": "plan-cell-foundation",
            "plan_path": "plans/cell-foundation.md",
            "plan_title": "Cell biology foundation",
            "desired_outcome": "Explain the first six chapters with synthesis notes.",
            "included_milestone_ids": [item["milestone_id"] for item in option["milestones"]],
            "included_action_ids": [item["task_id"] for item in decomposition["actions"]],
            "goal_updates": {"review_cadence": "monthly"},
        },
    )
    assert not (tmp_path / "plans" / "cell-foundation.md").exists()
    desktop = DesktopProposalService(vault_root=tmp_path, actor_id="tester")
    for action in ("submit", "approve", "apply"):
        challenge = desktop.prepare(proposal_id=proposal["proposal_id"], action=action)
        desktop.execute(proposal_id=proposal["proposal_id"], action=action, token=challenge.token)
    assert (tmp_path / "plans" / "cell-foundation.md").exists()
    assert "plan-cell-foundation" in (tmp_path / "goals" / "cell.md").read_text(encoding="utf-8")

    linked_session = app.dispatch(
        "copilot.session.start",
        {
            "goal_path": "goals/cell.md",
            "session_id": "session-cell-existing-plan",
        },
    )
    assert linked_session["readiness"]["path"] == "link-existing-plan"
    linked_options = app.dispatch(
        "copilot.options.generate",
        {
            "session_id": "session-cell-existing-plan",
            "as_of": "2026-07-17",
        },
    )
    assert linked_options["outcome"] == "link-existing-plan"
    assert linked_options["duplicate_findings"][0]["plan_id"] == "plan-cell-foundation"

    review = app.dispatch(
        "copilot.replanning.review",
        {
            "target_path": "plans/cell-foundation.md",
            "as_of": "2026-08-16",
            "corrections": [
                {
                    "evidence_id": "correction-capacity",
                    "kind": "correction",
                    "statement": "Available capacity changed from four hours to two hours weekly.",
                    "observed_at": "2026-08-16",
                }
            ],
            "recent_answers": [
                {
                    "evidence_id": "answer-prerequisite",
                    "kind": "review-answer",
                    "statement": "A prerequisite chapter now blocks the next wave.",
                }
            ],
        },
    )
    assert "revise-scope" in review["recommended_outcomes"]
    replanning = app.dispatch(
        "copilot.replanning.proposal.create",
        {
            "review_id": review["review_id"],
            "target_path": review["target_path"],
            "expected_hash": review["target_hash"],
            "outcome": "pause",
            "rationale": "Protect the goal while capacity and prerequisites are clarified.",
            "evidence_fingerprint": review["triggers"][0]["evidence_fingerprint"],
            "changes": {},
        },
    )
    assert desktop.inspect(replanning["proposal_id"]).status == "draft"
    assert "status: seed" in (tmp_path / "plans" / "cell-foundation.md").read_text(encoding="utf-8")


def test_experiment_park_abandon_and_no_plan_outcomes_are_durable(tmp_path: Path) -> None:
    _ready_vault(tmp_path)
    for suffix, outcome in (("experiment", "experiment"), ("park", "park"), ("abandon", "abandon")):
        service = PlanningSessionService(
            vault_root=tmp_path, runtime_dir=tmp_path / f".lifeos-{suffix}"
        )
        snapshot = service.start(goal_path="goals/cell.md", session_id=f"session-{suffix}")
        closed = service.close(
            session_id=f"session-{suffix}",
            outcome=outcome,
            label=f"Choose {outcome}",
            expected_revision=snapshot.envelope.session.source_revision,
        )
        assert closed.envelope.session.decisions[-1].kind == outcome
        assert not list((tmp_path / "plans").glob("*.md"))

    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos-reflect")
    snapshot = service.start(goal_path="goals/cell.md", session_id="session-reflect")
    closed = service.close(
        session_id="session-reflect",
        outcome="continue-reflecting",
        label="No plan yet",
        expected_revision=snapshot.envelope.session.source_revision,
    )
    assert closed.envelope.session.status == "closed"
    assert not list((tmp_path / "plans").glob("*.md"))


class FixtureAdapter:
    def synthesize(self, request):
        source = next(
            item.path for item in request.context.items if item.path == "wiki/cell-reading.md"
        )
        return (
            {
                "schema_version": 1,
                "option_id": "option-fixture-focused",
                "title": "Focused study wave",
                "strategy": "Study two chapters, then review comprehension.",
                "desired_outcome": "Explain two chapters from memory.",
                "boundaries": ["Protect exercise", "No full-book backlog"],
                "assumptions": [
                    {
                        "assumption_id": "assumption-fixture-capacity",
                        "statement": "Four hours remain available.",
                        "source_kind": "canonical-note",
                        "source_ref": request.goal.path,
                        "confidence": "medium",
                    }
                ],
                "success_evidence": ["Two synthesis notes"],
                "risks": ["The pace may still be dense"],
                "review_date": "2026-08-01",
                "milestones": [
                    {
                        "milestone_id": "milestone-fixture-first",
                        "title": "Build foundation",
                        "outcome": "Explain two chapters",
                        "wave": "current",
                    }
                ],
                "tradeoffs": ["Less breadth for faster feedback"],
                "unresolved_questions": [],
                "source_refs": [request.goal.path, source],
                "reasons_not_fit": ["May be too structured for exploration"],
                "confidence_label": "medium",
                "rejected_alternatives": ["Full-book plan"],
            },
            {
                "schema_version": 1,
                "option_id": "option-fixture-experiment",
                "title": "Prerequisite experiment",
                "strategy": "Test one prerequisite before committing to study pace.",
                "desired_outcome": "Know whether prerequisite knowledge is sufficient.",
                "boundaries": ["One week only"],
                "assumptions": [],
                "success_evidence": ["One self-test and review note"],
                "risks": ["Produces less immediate breadth"],
                "review_date": "2026-07-23",
                "milestones": [
                    {
                        "milestone_id": "milestone-fixture-test",
                        "title": "Run prerequisite test",
                        "outcome": "Resolve prerequisite uncertainty",
                        "wave": "current",
                    }
                ],
                "tradeoffs": ["Delays broader planning for better evidence"],
                "unresolved_questions": [],
                "source_refs": [request.goal.path],
                "reasons_not_fit": ["May be unnecessary if prerequisites are already known"],
                "confidence_label": "low",
                "rejected_alternatives": [],
            },
        )


class InvalidAdapter:
    def synthesize(self, request):
        return ({"schema_version": 1, "option_id": "invalid"},)


class TimeoutAdapter:
    def synthesize(self, request):
        raise TimeoutError("fixture timeout")


def test_provider_neutral_fixture_adapter_and_timeout_fallback(tmp_path: Path) -> None:
    _ready_vault(tmp_path)
    index = build_copilot_index(tmp_path)
    goal = index.goals[0]
    service = PlanningSessionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    snapshot = service.start(goal_path=goal.path, session_id="session-adapter")
    context = build_planning_context(
        vault_root=tmp_path,
        goal=goal,
        index=index,
        include_paths=("wiki/cell-reading.md",),
    )
    assisted = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
        adapter=FixtureAdapter(),
    )
    assert assisted.adapter_used is True and len(assisted.options) == 2
    assert assisted.options[0].strategy != assisted.options[1].strategy

    with pytest.raises(PlanOptionError):
        generate_plan_options(
            goal=goal,
            session=snapshot.envelope.session,
            readiness=snapshot.envelope.readiness,
            context=context,
            index=index,
            as_of=date(2026, 7, 16),
            adapter=InvalidAdapter(),
        )

    fallback = generate_plan_options(
        goal=goal,
        session=snapshot.envelope.session,
        readiness=snapshot.envelope.readiness,
        context=context,
        index=index,
        as_of=date(2026, 7, 16),
        adapter=TimeoutAdapter(),
    )
    assert fallback.adapter_used is False
    assert fallback.options and "adapter-fallback" in fallback.diagnostics[0]
