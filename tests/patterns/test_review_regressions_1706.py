from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.patterns import (
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.reviews import ReviewArtifactService, ReviewDecisionService
from lifeos.reviews.pattern_integration import build_review_snapshot, refresh_review_snapshot

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
WEEK_2 = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
WEEK_3 = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _pattern(vault: Path, pattern_id: str, *, evidence: tuple[PatternEvidence, ...] = ()) -> Path:
    metadata = PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id,
        description=f"Pattern {pattern_id}",
        status="needs-review",
        confidence="medium",
        review_reasons=("Existing review context.",),
        statement=f"Working hypothesis {pattern_id}.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-01T09:00:00Z",
        last_reviewed_at="2026-09-01T09:00:00Z",
        review_due_at=None,
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
        evaluation=None,
    )
    return _write(vault / "patterns" / f"{pattern_id}.md", serialize_pattern(metadata))


def _section(snapshot: object, section_id: str):
    return next(section for section in getattr(snapshot, "sections") if section.section_id == section_id)


def _open_week(
    service: ReviewArtifactService,
    runtime: Path,
    *,
    day: date,
    now: datetime,
    key: str,
):
    artifact = service.open_or_create(
        kind="weekly",
        day=day,
        timezone="UTC",
        now=now,
        idempotency_key=f"{key}-open",
    )
    return refresh_review_snapshot(
        service=service,
        artifact=artifact,
        runtime_dir=runtime,
        generated_at=now,
        idempotency_key=f"{key}-refresh",
    )


def test_protected_contesting_evidence_does_not_enter_review_scope(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _write(
        vault / "system" / "retrieval-policy.yml",
        "protected_prefixes:\n  - journal/private\n",
    )
    private = _write(
        vault / "journal" / "private" / "counter.md",
        "---\nid: private-counter\ntype: note\ntitle: Private\n---\nsecret counter evidence\n",
    )
    content = private.read_text(encoding="utf-8")
    import hashlib

    evidence = (
        PatternEvidence(
            path="journal/private/counter.md",
            source_id="private-counter",
            content_hash="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
            role="contesting",
        ),
    )
    target = _pattern(vault, "private-evidence", evidence=evidence)
    # Make the pattern quiet so the denied contesting source would be its only weekly reason.
    text = target.read_text(encoding="utf-8").replace("status: needs-review", "status: active").replace(
        "review_reasons:\n- Existing review context.\n", "review_reasons: []\n"
    )
    target.write_text(text, encoding="utf-8")

    snapshot = build_review_snapshot(
        vault_root=vault,
        runtime_dir=runtime,
        kind="weekly",
        day=date(2026, 9, 4),
        generated_at=NOW,
    )
    section = _section(snapshot, "personal-patterns-weekly")
    assert section.items == ()
    assert "journal/private/counter.md" not in repr(section)


def test_dismissal_remains_suppressed_across_more_than_one_later_review(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _pattern(vault, "tracked")
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)

    first, first_snapshot = _open_week(
        service, runtime, day=date(2026, 9, 4), now=NOW, key="week1"
    )
    item = _section(first_snapshot, "personal-patterns-weekly").items[0]
    ReviewDecisionService(service).decide(
        review_id=first.metadata.review_id,
        item_id=item.item_id,
        evidence_fingerprint=item.evidence_fingerprint,
        decision="dismiss_for_review",
        expected_hash=first.content_hash,
        idempotency_key="dismiss-week1",
        now=NOW,
    )

    _, second_snapshot = _open_week(
        service, runtime, day=date(2026, 9, 11), now=WEEK_2, key="week2"
    )
    assert _section(second_snapshot, "personal-patterns-weekly").items == ()

    _, third_snapshot = _open_week(
        service, runtime, day=date(2026, 9, 18), now=WEEK_3, key="week3"
    )
    assert _section(third_snapshot, "personal-patterns-weekly").items == ()


def test_weekly_limit_backfills_after_unchanged_dismissals(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    for index in range(9):
        _pattern(vault, f"pattern-{index:02d}")
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)

    first, first_snapshot = _open_week(
        service, runtime, day=date(2026, 9, 4), now=NOW, key="limit-week1"
    )
    items = _section(first_snapshot, "personal-patterns-weekly").items
    assert len(items) == 8
    decisions = ReviewDecisionService(service)
    current = first
    for index, item in enumerate(items):
        current = decisions.decide(
            review_id=current.metadata.review_id,
            item_id=item.item_id,
            evidence_fingerprint=item.evidence_fingerprint,
            decision="dismiss_for_review",
            expected_hash=current.content_hash,
            idempotency_key=f"dismiss-{index}",
            now=NOW,
        )

    _, second_snapshot = _open_week(
        service, runtime, day=date(2026, 9, 11), now=WEEK_2, key="limit-week2"
    )
    second_items = _section(second_snapshot, "personal-patterns-weekly").items
    assert [item.item_id for item in second_items] == ["personal-pattern:pattern-08"]
