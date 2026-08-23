from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.decisions import ReviewDecisionService, artifact_item_fingerprints
from lifeos.reviews.history import adjacent_reviews, link_review_history, list_review_history
from lifeos.reviews.snapshot import refresh_review_snapshot

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_history_links_and_orders_canonical_artifacts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    first = service.open_or_create(
        kind="daily", day=date(2026, 7, 15), timezone="UTC", now=NOW, idempotency_key="first"
    )
    second = service.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="second"
    )
    linked = link_review_history(service=service, artifact=second, now=NOW, idempotency_key="link")
    previous, following = adjacent_reviews(service=service, artifact=linked)
    assert previous and previous.metadata.review_id == first.metadata.review_id
    assert following is None
    assert linked.metadata.previous_review_id == first.metadata.review_id
    assert (
        service.load_id(first.metadata.review_id).metadata.next_review_id
        == second.metadata.review_id
    )
    assert [row.review_id for row in list_review_history(service=service)] == [
        second.metadata.review_id,
        first.metadata.review_id,
    ]


def test_unchanged_dismissal_is_suppressed_but_changed_evidence_returns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    first = service.open_or_create(
        kind="daily", day=date(2026, 7, 15), timezone="UTC", now=NOW, idempotency_key="first"
    )
    first, _ = refresh_review_snapshot(
        service=service,
        artifact=first,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh-first",
    )
    item_id, fingerprint = next(
        (key, value)
        for key, value in artifact_item_fingerprints(first).items()
        if key.startswith("inbox:")
    )
    first = ReviewDecisionService(service).decide(
        review_id=first.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        decision="dismiss_for_review",
        expected_hash=first.content_hash,
        idempotency_key="dismiss",
        now=NOW,
    )
    second = service.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="second"
    )
    second, _ = refresh_review_snapshot(
        service=service,
        artifact=second,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh-second",
    )
    assert item_id not in artifact_item_fingerprints(second)
    assert "Suppressed unchanged items" in second.body
    source = vault / "raw" / "idea.md"
    source.write_text(source.read_text() + "Changed evidence.\n", encoding="utf-8")
    second, _ = refresh_review_snapshot(
        service=service,
        artifact=second,
        runtime_dir=runtime,
        generated_at=datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc),
        idempotency_key="refresh-changed",
    )
    assert item_id in artifact_item_fingerprints(second)
    assert "evidence changed" in second.body


def test_carry_is_visible_without_copying_item_into_canonical_sources(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    first = service.open_or_create(
        kind="weekly", day=date(2026, 7, 8), timezone="UTC", now=NOW, idempotency_key="first"
    )
    first, _ = refresh_review_snapshot(
        service=service,
        artifact=first,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh-first",
    )
    item_id, fingerprint = next(
        (key, value)
        for key, value in artifact_item_fingerprints(first).items()
        if key.startswith("inbox:")
    )
    first = ReviewDecisionService(service).decide(
        review_id=first.metadata.review_id,
        item_id=item_id,
        evidence_fingerprint=fingerprint,
        decision="carry",
        expected_hash=first.content_hash,
        idempotency_key="carry",
        now=NOW,
    )
    second = service.open_or_create(
        kind="weekly", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="second"
    )
    second, _ = refresh_review_snapshot(
        service=service,
        artifact=second,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh-second",
    )
    assert "**carried**" in second.body
    assert "review_refs" not in (vault / "raw" / "idea.md").read_text()
