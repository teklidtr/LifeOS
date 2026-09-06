from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.ownership.manifest import serialize_generated_ownership_bytes
from lifeos.patterns import (
    PatternEvidence,
    PatternMetadata,
    PatternOrigin,
    compute_evidence_fingerprint,
    serialize_pattern,
)
from lifeos.patterns.contracts import PatternStatus
from lifeos.patterns.reviews import (
    DAILY_PATTERN_REVIEW_LIMIT,
    PATTERN_REVIEW_EVIDENCE_SOURCE_LIMIT,
    WEEKLY_PATTERN_REVIEW_LIMIT,
    create_pattern_review_proposal,
)
from lifeos.reviews import ReviewArtifactService, ReviewDecisionService
from lifeos.reviews.snapshot import build_review_snapshot, refresh_review_snapshot

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _metadata(
    pattern_id: str,
    *,
    status: PatternStatus = "active",
    evidence: tuple[PatternEvidence, ...] = (),
    review_due_at: str | None = None,
    last_reviewed_at: str | None = "2026-09-01T09:00:00Z",
) -> PatternMetadata:
    return PatternMetadata(
        pattern_id=pattern_id,
        title=pattern_id.replace("-", " ").title(),
        description=f"Reviewable working hypothesis for {pattern_id}.",
        status=status,
        confidence="medium",
        review_reasons=("Existing review context.",) if status == "needs-review" else (),
        statement=f"Working hypothesis for {pattern_id}.",
        origin=PatternOrigin("manual"),
        created_at="2026-09-01T09:00:00Z",
        updated_at="2026-09-01T09:00:00Z",
        last_reviewed_at=last_reviewed_at,
        review_due_at=review_due_at,
        evidence_fingerprint=compute_evidence_fingerprint(evidence),
        evidence=evidence,
        evaluation=None,
    )


def _write_pattern(
    vault: Path,
    pattern_id: str,
    *,
    status: PatternStatus = "active",
    evidence: tuple[PatternEvidence, ...] = (),
    review_due_at: str | None = None,
    last_reviewed_at: str | None = "2026-09-01T09:00:00Z",
) -> Path:
    metadata = _metadata(
        pattern_id,
        status=status,
        evidence=evidence,
        review_due_at=review_due_at,
        last_reviewed_at=last_reviewed_at,
    )
    return _write(vault / "patterns" / f"{pattern_id}.md", serialize_pattern(metadata))


def _section(snapshot: object, section_id: str):
    sections = getattr(snapshot, "sections")
    return next(section for section in sections if section.section_id == section_id)


def test_weekly_pattern_section_is_empty_without_patterns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    snapshot = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="weekly",
        day=date(2026, 9, 4),
        generated_at=NOW,
    )

    section = _section(snapshot, "personal-patterns-weekly")
    assert section.state == "empty"
    assert section.items == ()


def test_weekly_surfaces_due_contesting_and_new_seeds_but_not_quiet_active_patterns(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_pattern(vault, "due", review_due_at="2026-09-03T09:00:00Z")
    _write_pattern(vault, "quiet")
    contesting_source = (
        "---\nid: contesting-source\ntype: note\ntitle: Counter\n---\nCounter evidence.\n"
    )
    _write(vault / "raw" / "counter.md", contesting_source)
    contesting = (
        PatternEvidence(
            path="raw/counter.md",
            source_id="contesting-source",
            content_hash=_digest(contesting_source),
            role="contesting",
        ),
    )
    _write_pattern(vault, "contested", evidence=contesting)
    _write_pattern(vault, "seed", status="seed", last_reviewed_at=None)

    snapshot = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="weekly",
        day=date(2026, 9, 4),
        generated_at=NOW,
    )

    section = _section(snapshot, "personal-patterns-weekly")
    assert [item.item_id for item in section.items] == [
        "personal-pattern:due",
        "personal-pattern:contested",
        "personal-pattern:seed",
    ]
    assert "unresolved contesting evidence" in section.items[1].detail
    assert all(item.action == "open-source" for item in section.items)


def test_weekly_pattern_selection_is_bounded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for index in range(WEEKLY_PATTERN_REVIEW_LIMIT + 4):
        _write_pattern(vault, f"review-{index:02d}", status="needs-review")

    snapshot = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="weekly",
        day=date(2026, 9, 4),
        generated_at=NOW,
    )

    items = _section(snapshot, "personal-patterns-weekly").items
    assert len(items) == WEEKLY_PATTERN_REVIEW_LIMIT
    assert [item.item_id for item in items] == [
        f"personal-pattern:review-{index:02d}" for index in range(WEEKLY_PATTERN_REVIEW_LIMIT)
    ]


def test_daily_patterns_are_fail_closed_without_explicit_attention(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_pattern(vault, "due", review_due_at="2026-09-03T09:00:00Z")

    ordinary = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="daily",
        day=date(2026, 9, 4),
        generated_at=NOW,
    )
    assert _section(ordinary, "personal-patterns-daily").items == ()

    pinned = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="daily",
        day=date(2026, 9, 4),
        generated_at=NOW,
        pinned_pattern_ids=("due",),
    )
    items = _section(pinned, "personal-patterns-daily").items
    assert [item.item_id for item in items] == ["personal-pattern:due"]
    assert "explicitly pinned" in items[0].detail


def test_daily_explicit_attention_is_bounded_and_urgent_first(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    pattern_ids = tuple(f"pattern-{index}" for index in range(DAILY_PATTERN_REVIEW_LIMIT + 3))
    for pattern_id in pattern_ids:
        _write_pattern(vault, pattern_id)

    snapshot = build_review_snapshot(
        vault_root=vault,
        runtime_dir=tmp_path / "runtime",
        kind="daily",
        day=date(2026, 9, 4),
        generated_at=NOW,
        urgent_pattern_ids=(pattern_ids[-1],),
        pinned_pattern_ids=pattern_ids,
    )

    items = _section(snapshot, "personal-patterns-daily").items
    assert len(items) == DAILY_PATTERN_REVIEW_LIMIT
    assert items[0].item_id == f"personal-pattern:{pattern_ids[-1]}"
    assert "explicitly urgent" in items[0].detail


def test_dismissed_pattern_stays_suppressed_until_evidence_changes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    before = "---\nid: source-one\ntype: note\ntitle: Source\n---\nbefore\n"
    source = _write(vault / "journal" / "source.md", before)
    evidence = (
        PatternEvidence(
            path="journal/source.md",
            source_id="source-one",
            content_hash=_digest(before),
            role="supporting",
        ),
    )
    _write_pattern(vault, "tracked", status="needs-review", evidence=evidence)
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)

    first = service.open_or_create(
        kind="weekly",
        day=date(2026, 9, 4),
        timezone="UTC",
        now=NOW,
        idempotency_key="open-first",
    )
    first, first_snapshot = refresh_review_snapshot(
        service=service,
        artifact=first,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh-first",
    )
    first_item = _section(first_snapshot, "personal-patterns-weekly").items[0]
    assert len(first_item.sources) <= PATTERN_REVIEW_EVIDENCE_SOURCE_LIMIT + 1
    assert first_item.sources[1].path == "journal/source.md"
    ReviewDecisionService(service).decide(
        review_id=first.metadata.review_id,
        item_id=first_item.item_id,
        evidence_fingerprint=first_item.evidence_fingerprint,
        decision="dismiss_for_review",
        expected_hash=first.content_hash,
        idempotency_key="dismiss-first",
        now=NOW,
    )

    second = service.open_or_create(
        kind="weekly",
        day=date(2026, 9, 11),
        timezone="UTC",
        now=LATER,
        idempotency_key="open-second",
    )
    second, unchanged_snapshot = refresh_review_snapshot(
        service=service,
        artifact=second,
        runtime_dir=runtime,
        generated_at=LATER,
        idempotency_key="refresh-second",
    )
    assert _section(unchanged_snapshot, "personal-patterns-weekly").items == ()

    source.write_text(before.replace("before", "after"), encoding="utf-8")
    _, changed_snapshot = refresh_review_snapshot(
        service=service,
        artifact=second,
        runtime_dir=runtime,
        generated_at=LATER,
        idempotency_key="refresh-second-changed",
    )
    changed_items = _section(changed_snapshot, "personal-patterns-weekly").items
    assert [item.item_id for item in changed_items] == ["personal-pattern:tracked"]
    assert changed_items[0].evidence_fingerprint != first_item.evidence_fingerprint


def test_pattern_review_proposal_from_pinned_item_is_explicit_and_does_not_mutate_pattern(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    _write(
        vault / "system" / "generated-ownership.json",
        serialize_generated_ownership_bytes({}).decode("utf-8"),
    )
    target = _write_pattern(vault, "quiet")
    before = target.read_text(encoding="utf-8")
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    artifact = service.open_or_create(
        kind="daily",
        day=date(2026, 9, 4),
        timezone="UTC",
        now=NOW,
        idempotency_key="open",
    )
    artifact, snapshot = refresh_review_snapshot(
        service=service,
        artifact=artifact,
        runtime_dir=runtime,
        generated_at=NOW,
        idempotency_key="refresh",
        pinned_pattern_ids=("quiet",),
    )
    item = _section(snapshot, "personal-patterns-daily").items[0]
    assert "explicitly pinned" in item.detail

    result = create_pattern_review_proposal(
        vault_root=vault,
        runtime_dir=runtime,
        review=artifact,
        item_id=item.item_id,
        evidence_fingerprint=item.evidence_fingerprint,
        actor_id="pattern-reviewer",
        now=NOW,
    )

    proposal = vault / str(result["proposal_path"])
    assert (proposal / "proposal.md").exists()
    assert (proposal / "patches.json").exists()
    assert target.read_text(encoding="utf-8") == before
