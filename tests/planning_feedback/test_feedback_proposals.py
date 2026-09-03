from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.feedback import (
    DuplicateFeedbackProposal,
    FeedbackProposalError,
    FeedbackProposalRequest,
    create_feedback_proposal,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import approve_proposal, submit_proposal_for_review
from lifeos.proposals.loader import load_proposal_directory

NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


def plan(vault: Path) -> Path:
    (vault / "plans").mkdir(parents=True)
    path = vault / "plans" / "p.md"
    path.write_text(
        """---\nid: plan-p\ntype: plan\ntitle: Plan\nstatus: active\ngoal: goal-g\nreview_date: 2026-07-20\ntasks:\n  - task_id: t\n    title: Write note\n    status: todo\n    duration: 30\n    energy: medium\n    motivation: medium\n    mode: writing\n    blocked_by: []\n---\n# Plan\n""",
        encoding="utf-8",
    )
    return path


def body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


def request(kind: str, fingerprint: str, **kwargs: object) -> FeedbackProposalRequest:
    return FeedbackProposalRequest(
        kind,
        "plans/p.md",
        fingerprint,
        ("e1", "e2", "e3"),
        "moderate",
        "Make the next action fit observed execution.",
        ("Keep the current plan", "Pause and review"),
        **kwargs,
    )  # type: ignore[arg-type]


def assert_valid(vault: Path, proposal_id: str) -> None:
    loaded = load_proposal_directory(
        vault / "proposals" / proposal_id, proposals_root=vault / "proposals"
    )
    assert loaded.proposal is not None
    assert loaded.proposal.metadata.status.value == "draft"
    assert loaded.proposal.patch_document.operations[0].op == "patch_human_file"


def test_duration_clarification_blocker_pause_and_review_proposals(tmp_path: Path) -> None:
    for index, spec in enumerate(
        (
            request("update_task_estimate", "f-duration", task_id="t", changes={"duration": 45}),
            request(
                "clarify_task",
                "f-clarify",
                task_id="t",
                changes={"next_action": "Write the three-section outline"},
            ),
            request("add_blocker", "f-blocker", task_id="t", changes={"blocker": "read-source"}),
            request("pause_plan", "f-pause"),
            request("revise_review_date", "f-review", changes={"review_date": "2026-08-01"}),
            request("reduce_tracking", "f-tracking", changes={"frequency": "weekly"}),
            request("disable_tracking", "f-disable"),
        )
    ):
        vault = tmp_path / str(index)
        vault.mkdir()
        plan(vault)
        result = create_feedback_proposal(vault_root=vault, request=spec, actor_id="user", now=NOW)
        assert_valid(vault, result.proposal_id)
        assert "Explicit evidence" in (vault / result.proposal_path / "proposal.md").read_text()
        assert (vault / "plans" / "p.md").read_text().find("duration: 30") >= 0


def test_bounded_user_requested_decomposition_and_invalid_agent_output(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    plan(vault)
    good = request(
        "decompose_task",
        "f-decompose",
        task_id="t",
        decomposition_titles=("Outline", "Draft", "Edit"),
        agent_requested=True,
        changes={"user_requested_agent": True, "duration": 15},
    )
    result = create_feedback_proposal(vault_root=vault, request=good, actor_id="user", now=NOW)
    assert_valid(vault, result.proposal_id)
    bad_vault = tmp_path / "bad"
    bad_vault.mkdir()
    plan(bad_vault)
    bad = request(
        "decompose_task",
        "f-bad",
        task_id="t",
        decomposition_titles=("",),
        agent_requested=True,
        changes={"user_requested_agent": True},
    )
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(vault_root=bad_vault, request=bad, actor_id="user", now=NOW)


def test_duplicate_proposal_is_suppressed_until_evidence_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    plan(vault)
    spec = request("update_task_estimate", "fingerprint-1", task_id="t", changes={"duration": 45})
    create_feedback_proposal(vault_root=vault, request=spec, actor_id="user", now=NOW)
    with pytest.raises(DuplicateFeedbackProposal):
        create_feedback_proposal(vault_root=vault, request=spec, actor_id="user", now=NOW)
    changed = request(
        "update_task_estimate", "fingerprint-2", task_id="t", changes={"duration": 50}
    )
    result = create_feedback_proposal(vault_root=vault, request=changed, actor_id="user", now=NOW)
    assert result.evidence_fingerprint == "fingerprint-2"


def test_insufficient_or_invalid_change_does_not_publish(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    plan(vault)
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(
            vault_root=vault,
            request=request("update_task_estimate", "", task_id="t", changes={"duration": 45}),
            actor_id="user",
            now=NOW,
        )
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(
            vault_root=vault,
            request=request("update_task_estimate", "valid", task_id="t", changes={"duration": -1}),
            actor_id="user",
            now=NOW,
        )
    assert not (vault / "proposals").exists()


def test_resolve_blocker_and_task_fit_validation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    path = plan(vault)
    content = path.read_text(encoding="utf-8").replace(
        "blocked_by: []", "blocked_by:\n      - read-source"
    )
    path.write_text(content, encoding="utf-8")
    result = create_feedback_proposal(
        vault_root=vault,
        request=request(
            "resolve_blocker", "f-resolve", task_id="t", changes={"blocker": "read-source"}
        ),
        actor_id="user",
        now=NOW,
    )
    assert_valid(vault, result.proposal_id)

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    plan(invalid)
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(
            vault_root=invalid,
            request=request(
                "change_task_fit", "f-invalid-fit", task_id="t", changes={"energy": "impossible"}
            ),
            actor_id="user",
            now=NOW,
        )


def test_insufficient_confidence_and_missing_alternatives_are_suppressed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    plan(vault)
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(
            vault_root=vault,
            request=FeedbackProposalRequest(
                "update_task_estimate",
                "plans/p.md",
                "f-insufficient",
                ("e1",),
                "insufficient",
                "May fit better.",
                ("Keep current",),
                task_id="t",
                changes={"duration": 45},
            ),
            actor_id="user",
            now=NOW,
        )
    with pytest.raises(FeedbackProposalError):
        create_feedback_proposal(
            vault_root=vault,
            request=FeedbackProposalRequest(
                "update_task_estimate",
                "plans/p.md",
                "f-no-alternative",
                ("e1",),
                "moderate",
                "May fit better.",
                (),
                task_id="t",
                changes={"duration": 45},
            ),
            actor_id="user",
            now=NOW,
        )
    assert not (vault / "proposals").exists()


def test_feedback_proposal_uses_existing_lifecycle_and_applies(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = plan(vault)
    raw = target.read_bytes().decode("utf-8")
    parsed = parse_markdown_note(target, content=raw)
    prefix = raw[: len(raw) - len(parsed.body)]
    original_body = b"\r\n\r\nHuman proposal notes with hard break.  \r\n\tTail"
    target.write_bytes(prefix.encode("utf-8") + original_body)
    (vault / "system").mkdir()
    (vault / "system" / "generated-ownership.json").write_bytes(
        serialize_generated_ownership_bytes({})
    )
    result = create_feedback_proposal(
        vault_root=vault,
        request=request(
            "update_task_estimate",
            "f-lifecycle",
            task_id="t",
            changes={"duration": 45},
        ),
        actor_id="user",
        now=datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc),
    )
    assert body_bytes(target) == original_body
    root = vault / "proposals"
    proposal_dir = root / result.proposal_id
    draft = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert draft is not None
    submit_proposal_for_review(
        draft,
        proposals_root=root,
        submitted_by="user",
        submitted_at="2026-07-16T00:01:00Z",
    )
    pending = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert pending is not None
    approve_proposal(
        pending,
        proposals_root=root,
        approved_by="user",
        approved_at="2026-07-16T00:02:00Z",
    )
    approved = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert approved is not None

    applied = apply_proposal(
        approved,
        vault_root=vault,
        applied_by="user",
        applied_at="2026-07-16T00:03:00Z",
    )

    assert applied.changed_paths == ("plans/p.md",)
    assert "duration: 45" in target.read_text(encoding="utf-8")
    assert body_bytes(target) == original_body
