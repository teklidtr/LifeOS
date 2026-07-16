"""Dismissible daily and weekly rich-capture review sections."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from lifeos.reviews.contracts import ReviewItemSnapshot, ReviewSectionSnapshot, ReviewSourceReference, stable_fingerprint

from .artifact import CaptureArtifactService
from .contracts import CaptureError


def _source(path: str, content_hash: str, detail: str, at: str) -> tuple[ReviewSourceReference, ...]:
    return (ReviewSourceReference(path, content_hash, detail, at),)


def daily_capture_section(*, vault_root: Path, runtime_dir: Path, day: date, generated_at: datetime) -> ReviewSectionSnapshot:
    service = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        captures = service.list()
    except CaptureError as exc:
        return ReviewSectionSnapshot("rich-captures-daily", "Rich captures", True, "unavailable", (), exc.message)
    items = []
    for capture in captures:
        meta = capture.metadata
        if meta.exclude_from_reviews or meta.event_at[:10] != day.isoformat():
            continue
        detail_parts = [meta.capture_type]
        if meta.state in {"needs-review", "failed"}:
            detail_parts.append(meta.state)
        if meta.extraction_status in {"failed", "stale"} or meta.enrichment_status in {"failed", "stale"}:
            detail_parts.append("processing issue")
        if meta.derived_values and any(value.status == "suggested" for value in meta.derived_values):
            detail_parts.append("awaiting confirmation")
        detail = "; ".join(detail_parts)
        items.append(ReviewItemSnapshot(f"capture-day:{meta.capture_id}", "rich-captures-daily", meta.title, detail, stable_fingerprint(capture.path, capture.content_hash, detail), "ready", "open-source", _source(capture.path, capture.content_hash, detail, generated_at.isoformat())))
    return ReviewSectionSnapshot("rich-captures-daily", "Rich captures", True, "ready" if items else "empty", tuple(items))


def weekly_capture_section(*, vault_root: Path, runtime_dir: Path, range_start: date, range_end: date, generated_at: datetime) -> ReviewSectionSnapshot:
    service = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    try:
        captures = tuple(item for item in service.list() if range_start.isoformat() <= item.metadata.event_at[:10] <= range_end.isoformat() and not item.metadata.exclude_from_reviews)
    except CaptureError as exc:
        return ReviewSectionSnapshot("rich-captures-weekly", "Capture review", True, "unavailable", (), exc.message)
    if not captures:
        return ReviewSectionSnapshot("rich-captures-weekly", "Capture review", True, "empty")
    counts = {kind: sum(item.metadata.capture_type == kind for item in captures) for kind in ("meal", "exercise", "attachment", "mixed")}
    pending = sum(item.metadata.state in {"needs-review", "failed"} or any(value.status == "suggested" for value in item.metadata.derived_values) for item in captures)
    broken = sum(item.metadata.extraction_status in {"failed", "stale"} for item in captures)
    detail = f"{len(captures)} captures: {counts['meal']} meal, {counts['exercise']} exercise, {counts['attachment']} attachment, {counts['mixed']} mixed; {pending} awaiting review; {broken} extraction issue(s)."
    sources = tuple(ReviewSourceReference(item.path, item.content_hash, item.metadata.capture_type, generated_at.isoformat()) for item in captures[:50])
    item = ReviewItemSnapshot("capture-week:summary", "rich-captures-weekly", "Capture activity", detail, stable_fingerprint(*(f"{entry.path}:{entry.content_hash}" for entry in captures), detail), "ready", "open-capture-gallery", sources)
    return ReviewSectionSnapshot("rich-captures-weekly", "Capture review", True, "ready", (item,))
