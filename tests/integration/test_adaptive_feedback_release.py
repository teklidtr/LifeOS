from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

import lifeos.proposals.application as application_module
from lifeos.bridge import BridgeApplication
from lifeos.daily import content_hash
from lifeos.feedback import (
    FeedbackObservation,
    FeedbackProposalRequest,
    ReplayContext,
    build_evidence_dataset,
    create_feedback_proposal,
    replay_history,
)
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.planning import PlanningAction
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import approve_proposal, submit_proposal_for_review
from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.recovery import discover_recovery_state, unresolved_recovery_journals

FIXTURES = Path(__file__).parent / "fixtures" / "feedback"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _write_plan(vault: Path, events: list[dict[str, object]]) -> Path:
    (vault / "plans").mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "id": "plan-writing",
        "type": "plan",
        "title": "Writing plan",
        "status": "active",
        "goal": "goal-write",
        "tasks": [
            {
                "task_id": "write-note",
                "title": "Write note",
                "status": "todo",
                "duration": 30,
                "energy": "medium",
                "motivation": "medium",
                "mode": "writing",
                "blocked_by": [],
            }
        ],
        "execution_history": [
            {
                "schema_version": 1,
                "task_id": "write-note",
                **event,
            }
            for event in events
        ],
    }
    path = vault / "plans" / "writing.md"
    path.write_text(
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n# Writing plan\n",
        encoding="utf-8",
    )
    return path


def _prepare_vault(
    tmp_path: Path, fixture: str = "consistent-underestimation"
) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    path = _write_plan(vault, _fixture(fixture)["events"])  # type: ignore[arg-type]
    (vault / "system").mkdir()
    (vault / "system" / "generated-ownership.json").write_bytes(
        serialize_generated_ownership_bytes({})
    )
    return vault, runtime, path


def _mode(bridge: BridgeApplication, mode: str, key: str) -> dict[str, object]:
    current = bridge.dispatch("feedback.preferences.get", {})
    assert isinstance(current, dict)
    updated = bridge.dispatch(
        "feedback.preferences.update",
        {
            "idempotency_key": key,
            "expected_hash": current.get("content_hash"),
            "mode": mode,
        },
    )
    assert isinstance(updated, dict)
    return updated


def test_complete_daily_feedback_loop_off_shadow_active_and_restart(tmp_path: Path) -> None:
    vault, runtime, plan_path = _prepare_vault(tmp_path)
    bridge = BridgeApplication(vault_root=vault, runtime_dir=runtime, actor_id="integration-user")

    for index, mode in enumerate(("off", "shadow", "active"), start=1):
        _mode(bridge, mode, f"mode-{index}")
        dashboard = bridge.dispatch(
            "today.get",
            {
                "day": "2026-07-16",
                "available_minutes": 50,
                "energy": "medium",
                "motivation": "medium",
            },
        )
        assert isinstance(dashboard, dict)
        planning = dashboard["planning"]
        assert isinstance(planning, dict)
        feedback = planning["data"]["adaptive_feedback"]
        assert feedback["mode"] == mode
        if mode == "shadow":
            assert feedback["returned"] == feedback["baseline"]
        if mode == "active":
            assert feedback["returned"] == feedback["adaptive"]

    current = bridge.dispatch("feedback.preferences.get", {})
    assert isinstance(current, dict)
    bridge.dispatch(
        "feedback.preferences.update",
        {
            "idempotency_key": "exclude-u1",
            "expected_hash": current["content_hash"],
            "exclude_event_id": "u1",
        },
    )
    plan_hash = content_hash(plan_path.read_text(encoding="utf-8"))
    corrected = bridge.dispatch(
        "feedback.outcome.correct",
        {
            "idempotency_key": "correct-u2",
            "plan_path": "plans/writing.md",
            "corrects_event_id": "u2",
            "outcome": "done",
            "day": "2026-07-03",
            "expected_hash": plan_hash,
            "actual_minutes": 30,
            "completion_fraction": 1.0,
            "reason": "The timer had included a break.",
        },
    )
    assert corrected["corrects_event_id"] == "u2"

    current = bridge.dispatch("feedback.preferences.get", {})
    assert isinstance(current, dict)
    bridge.dispatch(
        "feedback.preferences.update",
        {
            "idempotency_key": "reset-boundary",
            "expected_hash": current["content_hash"],
            "reset_before": "2026-07-04",
            "reset_reason": "Routine changed.",
        },
    )
    bridge.dispatch("feedback.reset", {})

    restarted = BridgeApplication(
        vault_root=vault, runtime_dir=runtime, actor_id="integration-user"
    )
    preferences = restarted.dispatch("feedback.preferences.get", {})
    assert preferences["mode"] == "active"
    assert preferences["reset_before"] == date(2026, 7, 4)
    dataset = restarted.dispatch("feedback.dataset.rebuild", {"as_of": "2026-07-16"})
    observations = dataset["dataset"]["observations"]
    assert any(item["event_id"] == "u1" and item["excluded"] for item in observations)
    assert any(item["event_id"] == "correct-u2" and item["excluded"] for item in observations)

    replay = restarted.dispatch(
        "feedback.replay",
        {
            "mode": "shadow",
            "contexts": [
                {
                    "day": "2026-07-16",
                    "available_minutes": 50,
                    "energy": "medium",
                    "motivation": "medium",
                }
            ],
        },
    )
    assert replay["mode"] == "shadow"
    assert "productivity score" not in json.dumps(replay, default=str).casefold()


@pytest.mark.parametrize(
    "name",
    (
        "sparse",
        "consistent-underestimation",
        "inconsistent",
        "changing-routine",
        "repeated-avoidance",
        "corrected-retracted",
        "missing-malformed",
        "long-inactivity",
    ),
)
def test_fixture_histories_rebuild_without_mutation(tmp_path: Path, name: str) -> None:
    vault = tmp_path / name
    vault.mkdir()
    path = _write_plan(vault, _fixture(name)["events"])  # type: ignore[arg-type]
    before = path.read_bytes()

    dataset = build_evidence_dataset(vault, as_of=date(2026, 7, 16))

    assert dataset.source_fingerprint
    assert path.read_bytes() == before
    if name == "missing-malformed":
        assert any(item.code == "invalid_event_date" for item in dataset.diagnostics)
    if name == "corrected-retracted":
        assert dataset.corrected_event_count == 1
        assert dataset.retracted_event_count == 1


def test_changing_routine_ignores_stale_history(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_plan(vault, _fixture("changing-routine")["events"])  # type: ignore[arg-type]
    dataset = build_evidence_dataset(vault, as_of=date(2026, 7, 16))
    action = PlanningAction(
        "write-note",
        "Write note",
        "todo",
        30,
        "medium",
        "medium",
        "writing",
        "goal-write",
        "plan-writing",
        None,
        (),
        "plans/writing.md",
    )

    replay = replay_history(
        actions=(action,),
        observations=dataset.observations,
        contexts=(ReplayContext(date(2026, 7, 16), 60),),
        mode="shadow",
    )

    assert replay.days[0].changed_task_ids == ()


class _InjectedInterruption(BaseException):
    pass


def test_feedback_proposal_recovers_after_interrupted_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _, _ = _prepare_vault(tmp_path)
    result = create_feedback_proposal(
        vault_root=vault,
        request=FeedbackProposalRequest(
            "update_task_estimate",
            "plans/writing.md",
            "release-proposal-fingerprint",
            ("u1", "u2", "u3", "u4"),
            "moderate",
            "Use a more realistic writing window.",
            ("Keep the current estimate", "Decompose the task"),
            task_id="write-note",
            changes={"duration": 55},
        ),
        actor_id="integration-user",
        now=datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
    )
    root = vault / "proposals"
    proposal_dir = root / result.proposal_id
    draft = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert draft is not None
    submit_proposal_for_review(
        draft,
        proposals_root=root,
        submitted_by="integration-user",
        submitted_at="2026-07-16T00:01:00Z",
    )
    pending = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert pending is not None
    approve_proposal(
        pending,
        proposals_root=root,
        approved_by="integration-user",
        approved_at="2026-07-16T00:02:00Z",
    )
    approved = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert approved is not None

    def interrupt(name: str) -> None:
        if name == "after_target_install:0":
            raise _InjectedInterruption()

    monkeypatch.setattr(application_module, "_application_checkpoint", interrupt)
    with pytest.raises(_InjectedInterruption):
        apply_proposal(
            approved,
            vault_root=vault,
            applied_by="integration-user",
            applied_at="2026-07-16T00:03:00Z",
        )
    discovery = discover_recovery_state(recovery_root=vault / ".lifeos" / "recovery")
    assert len(unresolved_recovery_journals(discovery)) == 1

    monkeypatch.setattr(application_module, "_application_checkpoint", lambda _name: None)
    approved = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert approved is not None
    applied = apply_proposal(
        approved,
        vault_root=vault,
        applied_by="integration-user",
        applied_at="2026-07-16T00:04:00Z",
    )

    assert applied.changed_paths == ("plans/writing.md",)
    assert "duration: 55" in (vault / "plans" / "writing.md").read_text(encoding="utf-8")
    discovery = discover_recovery_state(recovery_root=vault / ".lifeos" / "recovery")
    assert unresolved_recovery_journals(discovery) == ()


def test_replay_large_history_stays_within_documented_budget() -> None:
    action = PlanningAction(
        "write-note",
        "Write note",
        "todo",
        30,
        "medium",
        "medium",
        "writing",
        "goal",
        "plan",
        None,
        (),
        "plans/p.md",
    )
    observations = tuple(
        FeedbackObservation(
            1,
            f"obs-{index}",
            f"e{index}",
            "plans/p.md",
            f"hash-{index}",
            index,
            date(2026, 1 + ((index // 28) % 6), 1 + (index % 28)),
            "plan",
            "goal",
            "write-note",
            "Write note",
            "writing",
            "writing",
            "medium",
            "medium",
            False,
            "done",
            1.0,
            30,
            30 + (index % 10),
            "medium",
            "medium",
            "medium",
            None,
            None,
            None,
            (),
        )
        for index in range(3000)
    )
    started = time.perf_counter()
    replay_history(
        actions=(action,),
        observations=observations,
        contexts=(ReplayContext(date(2026, 7, 16), 120),),
        mode="shadow",
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0
