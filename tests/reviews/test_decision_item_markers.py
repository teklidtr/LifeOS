from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.artifact import ReviewArtifactUpdate
from lifeos.reviews.contracts import ReviewArtifact
from lifeos.reviews.decisions import ReviewDecisionService, artifact_item_fingerprints
from lifeos.reviews.snapshot import refresh_review_snapshot

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
FP_A = "sha256:" + "a" * 64
FP_B = "sha256:" + "b" * 64


def marker(item_id: str, fingerprint: str = FP_A) -> str:
    return f"<!-- lifeos:item {item_id} {fingerprint} -->"


def setup_artifact(tmp_path: Path) -> tuple[Path, ReviewArtifactService, ReviewArtifact]:
    vault = tmp_path / "vault"
    vault.mkdir()
    artifacts = ReviewArtifactService(
        vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="me"
    )
    artifact = artifacts.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="UTC",
        now=NOW,
        idempotency_key="open",
    )
    return vault, artifacts, artifact


def replace_items(
    artifacts: ReviewArtifactService,
    artifact: ReviewArtifact,
    content: str,
    *,
    idempotency_key: str,
) -> ReviewArtifact:
    return artifacts.update(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key=idempotency_key,
        now=NOW,
        update=ReviewArtifactUpdate(managed_blocks={"items": content}),
    )


def test_item_scanner_accepts_only_structural_top_level_checkbox_lines(tmp_path: Path) -> None:
    _, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            f"Inline example {marker('inline')}",
            f"> - [ ] Quoted example {marker('quoted')}",
            f"  - [ ] Nested list example {marker('nested')}",
            f"    - [ ] Indented code example {marker('indented')}",
            f"\t- [ ] Tab-indented example {marker('tabbed')}",
            f"-     [ ] Code-like list content {marker('wide-separator')}",
            f"-\t[ ] Tab-separated list content {marker('tab-separator')}",
            f"- [ ] Marker is not trailing {marker('middle')} extra text",
            "````markdown",
            f"- [ ] Fenced example {marker('fenced')}",
            "````not-a-closer",
            f"- [ ] Still fenced after false closer {marker('false-closer')}",
            "`````",
            "~~~",
            f"- [ ] Tilde-fenced example {marker('tilde-fenced')}",
            "~~~~",
            f"- [ ] Real item {marker('real', FP_B)}",
        )
    )
    artifact = replace_items(
        artifacts, artifact, items, idempotency_key="structural-items"
    )

    assert artifact_item_fingerprints(artifact) == {"real": FP_B}


@pytest.mark.parametrize(
    ("second_fingerprint", "case"),
    ((FP_A, "same"), (FP_B, "different")),
)
def test_duplicate_structural_item_ids_fail_before_canonical_mutation(
    tmp_path: Path, second_fingerprint: str, case: str
) -> None:
    vault, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            f"- [ ] First copy {marker('duplicate', FP_A)}",
            f"- [ ] Second copy {marker('duplicate', second_fingerprint)}",
        )
    )
    artifact = replace_items(
        artifacts, artifact, items, idempotency_key=f"duplicate-items-{case}"
    )
    path = vault / artifact.path
    before = path.read_bytes()
    before_decisions = artifact.metadata.item_decisions
    before_refs = artifact.metadata.proposal_refs

    with pytest.raises(DailyInteractionError) as error:
        ReviewDecisionService(artifacts).decide(
            review_id=artifact.metadata.review_id,
            item_id="duplicate",
            evidence_fingerprint=FP_A,
            decision="carry",
            expected_hash=artifact.content_hash,
            idempotency_key=f"duplicate-decision-{case}",
            now=NOW,
        )

    assert error.value.code == "duplicate_review_item"
    assert path.read_bytes() == before
    reloaded = artifacts.load_id(artifact.metadata.review_id)
    assert reloaded.metadata.item_decisions == before_decisions
    assert reloaded.metadata.proposal_refs == before_refs


def test_multiple_markers_on_one_item_line_fail_closed(tmp_path: Path) -> None:
    _, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            f"- [ ] Ambiguous {marker('first', FP_A)} {marker('second', FP_B)}",
        )
    )
    artifact = replace_items(
        artifacts, artifact, items, idempotency_key="ambiguous-item-line"
    )

    with pytest.raises(DailyInteractionError) as error:
        artifact_item_fingerprints(artifact)

    assert error.value.code == "duplicate_review_item"


def test_fenced_fake_marker_cannot_attach_proposal_reference(tmp_path: Path) -> None:
    vault, artifacts, artifact = setup_artifact(tmp_path)
    items = "\n".join(
        (
            "## Review items",
            "",
            "````markdown",
            f"- [ ] Example only {marker('fake-proposal', FP_A)}",
            "````not-a-closer",
            f"- [ ] Still example only {marker('still-fake', FP_B)}",
            "`````",
        )
    )
    artifact = replace_items(
        artifacts, artifact, items, idempotency_key="fake-proposal-items"
    )
    path = vault / artifact.path
    before = path.read_bytes()
    before_decisions = artifact.metadata.item_decisions
    before_refs = artifact.metadata.proposal_refs

    with pytest.raises(DailyInteractionError) as error:
        ReviewDecisionService(artifacts).decide(
            review_id=artifact.metadata.review_id,
            item_id="fake-proposal",
            evidence_fingerprint=FP_A,
            decision="propose_change",
            proposal_id="proposal-fake",
            expected_hash=artifact.content_hash,
            idempotency_key="reject-fake-proposal",
            now=NOW,
        )

    assert error.value.code == "stale_review_item"
    assert path.read_bytes() == before
    reloaded = artifacts.load_id(artifact.metadata.review_id)
    assert reloaded.metadata.item_decisions == before_decisions
    assert reloaded.metadata.proposal_refs == before_refs


def test_multiline_source_title_keeps_rendered_item_authorizable(tmp_path: Path) -> None:
    vault, artifacts, artifact = setup_artifact(tmp_path)
    raw = vault / "raw" / "idea.md"
    raw.parent.mkdir(parents=True)
    raw.write_text(
        "---\ntype: raw\ntitle: |-\n  First line\n  Second line\nstatus: inbox\n---\n",
        encoding="utf-8",
    )
    artifact, _ = refresh_review_snapshot(
        service=artifacts,
        artifact=artifact,
        runtime_dir=tmp_path / "runtime",
        generated_at=NOW,
        idempotency_key="multiline-refresh",
    )
    items = artifact_item_fingerprints(artifact)
    item_id, fingerprint = next(
        (item_id, fingerprint)
        for item_id, fingerprint in items.items()
        if item_id.startswith("inbox:")
    )

    assert "- [ ] First line Second line <!-- lifeos:item " in artifact.body
    updated = ReviewDecisionService(artifacts).decide(
        review_id=artifact.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        decision="acknowledge",
        expected_hash=artifact.content_hash,
        idempotency_key="multiline-decision",
        now=NOW,
    )
    assert any(decision.item_id == item_id for decision in updated.metadata.item_decisions)
