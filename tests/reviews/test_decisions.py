from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError, content_hash
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
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")


def setup(tmp_path: Path):
    vault = tmp_path / "vault"; vault.mkdir(); runtime = tmp_path / "runtime"
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    artifacts = ReviewArtifactService(vault_root=vault, runtime_dir=runtime, actor_id="me")
    artifact = artifacts.open_or_create(kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open")
    artifact, _ = refresh_review_snapshot(service=artifacts, artifact=artifact, runtime_dir=runtime, generated_at=NOW, idempotency_key="refresh")
    return vault, runtime, artifacts, artifact


def test_review_decision_is_scoped_to_visible_evidence(tmp_path: Path) -> None:
    _, _, artifacts, artifact = setup(tmp_path)
    items = artifact_item_fingerprints(artifact)
    item_id, fingerprint = next((key, value) for key, value in items.items() if key.startswith("inbox:"))
    decisions = ReviewDecisionService(artifacts)
    updated = decisions.decide(review_id=artifact.metadata.review_id, item_id=item_id, evidence_fingerprint=fingerprint, decision="carry", expected_hash=artifact.content_hash, idempotency_key="decide", now=NOW, note="Review tomorrow")
    assert updated.metadata.item_decisions[0].decision == "carry"
    with pytest.raises(DailyInteractionError) as stale:
        decisions.decide(review_id=updated.metadata.review_id, item_id=item_id, evidence_fingerprint="sha256:" + "0" * 64, decision="acknowledge", expected_hash=updated.content_hash, idempotency_key="stale", now=NOW)
    assert stale.value.code == "stale_review_item"


def test_review_proposal_is_draft_and_does_not_mutate_target(tmp_path: Path) -> None:
    vault, _, artifacts, artifact = setup(tmp_path)
    item_id, fingerprint = next((key, value) for key, value in artifact_item_fingerprints(artifact).items() if key.startswith("inbox:"))
    target = vault / "raw" / "idea.md"; original = target.read_text()
    result = create_review_proposal(vault_root=vault, actor_id="me", now=NOW, request=ReviewProposalRequest(
        review_id=artifact.metadata.review_id, item_id=item_id, evidence_fingerprint=fingerprint,
        target_path="raw/idea.md", expected_target_hash="sha256:" + content_hash(original),
        action="set_note_status", value="archived", rationale="The capture was reviewed and is no longer actionable.",
    ))
    assert target.read_text() == original
    loaded = load_proposal_directory(vault / result.proposal_path, proposals_root=vault / "proposals")
    assert loaded.proposal is not None and loaded.proposal.metadata.status == "draft"
    assert loaded.proposal.metadata.extensions["review_artifact"]["review_id"] == artifact.metadata.review_id
    decisions = ReviewDecisionService(artifacts)
    attached = decisions.decide(review_id=artifact.metadata.review_id, item_id=item_id, evidence_fingerprint=fingerprint, decision="propose_change", proposal_id=result.proposal_id, expected_hash=artifact.content_hash, idempotency_key="attach", now=NOW)
    assert attached.metadata.proposal_refs == (result.proposal_id,)
    assert attached.metadata.item_decisions[0].proposal_id == result.proposal_id


def test_proposal_rejects_stale_target_noop_and_duplicate_evidence(tmp_path: Path) -> None:
    vault, _, _, artifact = setup(tmp_path)
    item_id, fingerprint = next((key, value) for key, value in artifact_item_fingerprints(artifact).items() if key.startswith("inbox:"))
    base = ReviewProposalRequest(review_id=artifact.metadata.review_id, item_id=item_id, evidence_fingerprint=fingerprint, target_path="raw/idea.md", expected_target_hash="sha256:" + "0" * 64, action="set_note_status", value="archived", rationale="Reviewed")
    with pytest.raises(ReviewProposalError, match="changed"):
        create_review_proposal(vault_root=vault, request=base, actor_id="me", now=NOW)
    actual = "sha256:" + content_hash((vault / "raw" / "idea.md").read_text())
    valid = ReviewProposalRequest(**{**base.__dict__, "expected_target_hash": actual}) if hasattr(base, "__dict__") else ReviewProposalRequest(base.review_id, base.item_id, base.evidence_fingerprint, base.target_path, actual, base.action, base.value, base.rationale, base.task_id)
    create_review_proposal(vault_root=vault, request=valid, actor_id="me", now=NOW)
    with pytest.raises(DuplicateReviewProposal):
        create_review_proposal(vault_root=vault, request=valid, actor_id="me", now=NOW)
