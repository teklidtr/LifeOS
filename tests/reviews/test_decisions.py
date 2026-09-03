from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.proposals.application import apply_proposal
from lifeos.proposals.lifecycle import approve_proposal, submit_proposal_for_review
from lifeos.proposals.loader import load_proposal_directory
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.decisions import (
    DuplicateReviewProposal,
    ReviewDecisionService,
    ReviewProposalError,
    ReviewProposalRequest,
    artifact_item_fingerprints,
    create_review_proposal,
)
from lifeos.reviews.snapshot import refresh_review_snapshot

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


def setup(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write(
        vault / "raw" / "idea.md",
        "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n\n\n"
        "Human review target with hard break.  \n\tTail",
    )
    artifacts = ReviewArtifactService(vault_root=vault, runtime_dir=runtime, actor_id="me")
    artifact = artifacts.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open"
    )
    artifact, _ = refresh_review_snapshot(
        service=artifacts,
        artifact=artifact,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh",
    )
    return vault, runtime, artifacts, artifact


def test_review_decision_is_scoped_to_visible_evidence(tmp_path: Path) -> None:
    _, _, artifacts, artifact = setup(tmp_path)
    items = artifact_item_fingerprints(artifact)
    item_id, fingerprint = next(
        (key, value) for key, value in items.items() if key.startswith("inbox:")
    )
    decisions = ReviewDecisionService(artifacts)
    updated = decisions.decide(
        review_id=artifact.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        decision="carry",
        expected_hash=artifact.content_hash,
        idempotency_key="decide",
        now=NOW,
        note="Review tomorrow",
    )
    assert updated.metadata.item_decisions[0].decision == "carry"
    with pytest.raises(DailyInteractionError) as stale:
        decisions.decide(
            review_id=updated.metadata.review_id,
            item_id=item_id,
            evidence_fingerprint="sha256:" + "0" * 64,
            decision="acknowledge",
            expected_hash=updated.content_hash,
            idempotency_key="stale",
            now=NOW,
        )
    assert stale.value.code == "stale_review_item"


def test_review_proposal_is_draft_and_preserves_target_body_through_apply(tmp_path: Path) -> None:
    vault, _, artifacts, artifact = setup(tmp_path)
    item_id, fingerprint = next(
        (key, value)
        for key, value in artifact_item_fingerprints(artifact).items()
        if key.startswith("inbox:")
    )
    target = vault / "raw" / "idea.md"
    original = target.read_bytes()
    original_body = body_bytes(target)
    result = create_review_proposal(
        vault_root=vault,
        actor_id="me",
        now=NOW,
        request=ReviewProposalRequest(
            review_id=artifact.metadata.review_id,
            item_id=item_id,
            evidence_fingerprint=fingerprint,
            target_path="raw/idea.md",
            expected_target_hash="sha256:" + content_hash(original),
            action="set_note_status",
            value="archived",
            rationale="The capture was reviewed and is no longer actionable.",
        ),
    )
    assert target.read_bytes() == original
    root = vault / "proposals"
    proposal_dir = vault / result.proposal_path
    loaded = load_proposal_directory(proposal_dir, proposals_root=root)
    assert loaded.proposal is not None and loaded.proposal.metadata.status == "draft"
    assert (
        loaded.proposal.metadata.extensions["review_artifact"]["review_id"]
        == artifact.metadata.review_id
    )

    (vault / "system").mkdir()
    (vault / "system" / "generated-ownership.json").write_bytes(
        serialize_generated_ownership_bytes({})
    )
    submit_proposal_for_review(
        loaded.proposal,
        proposals_root=root,
        submitted_by="me",
        submitted_at="2026-07-16T12:01:00Z",
    )
    pending = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert pending is not None
    approve_proposal(
        pending,
        proposals_root=root,
        approved_by="me",
        approved_at="2026-07-16T12:02:00Z",
    )
    approved = load_proposal_directory(proposal_dir, proposals_root=root).proposal
    assert approved is not None
    apply_proposal(
        approved,
        vault_root=vault,
        applied_by="me",
        applied_at="2026-07-16T12:03:00Z",
    )
    assert body_bytes(target) == original_body
    assert b"status: archived" in target.read_bytes()

    decisions = ReviewDecisionService(artifacts)
    attached = decisions.decide(
        review_id=artifact.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        decision="propose_change",
        proposal_id=result.proposal_id,
        expected_hash=artifact.content_hash,
        idempotency_key="attach",
        now=NOW,
    )
    assert attached.metadata.proposal_refs == (result.proposal_id,)
    assert attached.metadata.item_decisions[0].proposal_id == result.proposal_id


def test_proposal_rejects_stale_target_noop_and_duplicate_evidence(tmp_path: Path) -> None:
    vault, _, _, artifact = setup(tmp_path)
    item_id, fingerprint = next(
        (key, value)
        for key, value in artifact_item_fingerprints(artifact).items()
        if key.startswith("inbox:")
    )
    base = ReviewProposalRequest(
        review_id=artifact.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        target_path="raw/idea.md",
        expected_target_hash="sha256:" + "0" * 64,
        action="set_note_status",
        value="archived",
        rationale="Reviewed",
    )
    target = vault / "raw" / "idea.md"
    unchanged = target.read_bytes()
    with pytest.raises(ReviewProposalError, match="changed"):
        create_review_proposal(vault_root=vault, request=base, actor_id="me", now=NOW)
    assert target.read_bytes() == unchanged
    actual = "sha256:" + content_hash(target.read_bytes())
    valid = (
        ReviewProposalRequest(**{**base.__dict__, "expected_target_hash": actual})
        if hasattr(base, "__dict__")
        else ReviewProposalRequest(
            base.review_id,
            base.item_id,
            base.evidence_fingerprint,
            base.target_path,
            actual,
            base.action,
            base.value,
            base.rationale,
            base.task_id,
        )
    )
    create_review_proposal(vault_root=vault, request=valid, actor_id="me", now=NOW)
    with pytest.raises(DuplicateReviewProposal):
        create_review_proposal(vault_root=vault, request=valid, actor_id="me", now=NOW)
