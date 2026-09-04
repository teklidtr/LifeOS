"""Bounded personal-pattern evidence for canonical daily and weekly reviews."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from lifeos.daily.errors import DailyInteractionError
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.registry_tools import refresh_registry
from lifeos.registry import Registry
from lifeos.reviews.contracts import (
    ReviewArtifact,
    ReviewItemSnapshot,
    ReviewSectionSnapshot,
    ReviewSourceReference,
    stable_fingerprint,
)
from lifeos.reviews.decisions import artifact_item_fingerprints

from .contracts import PatternError
from .model import (
    PersonalModelDocument,
    PersonalModelError,
    PersonalModelItem,
    build_personal_model_document,
)
from .review import PatternReviewService

WEEKLY_PATTERN_REVIEW_LIMIT = 8
DAILY_PATTERN_REVIEW_LIMIT = 3

_WEEKLY_SECTION_ID = "personal-patterns-weekly"
_DAILY_SECTION_ID = "personal-patterns-daily"
_ITEM_PREFIX = "personal-pattern:"
_MATERIAL_REVIEW_CODES = frozenset(
    {
        "evidence-fingerprint-changed",
        "materially-new-evidence",
        "changed-evidence",
        "moved-evidence",
        "missing-evidence",
        "deleted-evidence",
        "ambiguous-evidence",
        "weaker-evidence",
        "direction-reversal",
        "new-counter-evidence",
        "stale-evidence",
    }
)


def _allow_all(_path: str) -> bool:
    return True


def _review_model(
    *, vault_root: Path, runtime_dir: Path, generated_at: datetime
) -> PersonalModelDocument:
    registry = Registry(runtime_dir / "registry.db")
    # Pattern review depends on current file identity and content hashes. Refresh only
    # deterministic file facts here; proposal indexing is unrelated to this snapshot.
    refresh_registry(
        vault_root=vault_root,
        registry=registry,
        identity_allow_path=_allow_all,
    )
    return build_personal_model_document(
        vault_root=vault_root,
        registry=registry,
        allow_path=_allow_all,
        now=generated_at,
    )


def _diagnostic_part(item: PersonalModelItem) -> tuple[str, ...]:
    return tuple(
        "|".join(
            (
                diagnostic.reference.role,
                diagnostic.reference.path,
                diagnostic.reference.content_hash,
                diagnostic.state,
                diagnostic.current_path or "",
                diagnostic.current_content_hash or "",
                ",".join(diagnostic.candidate_paths),
            )
        )
        for diagnostic in sorted(
            item.evidence_diagnostics,
            key=lambda value: (
                value.reference.role,
                value.reference.path,
                value.reference.content_hash,
            ),
        )
    )


def pattern_review_fingerprint(item: PersonalModelItem) -> str:
    """Fingerprint only the review-relevant pattern context, not arbitrary note prose."""
    trigger_parts = tuple(
        f"{reason.code}|{reason.summary}|{','.join(reason.evidence_paths)}"
        for reason in item.review_trigger_reasons
    )
    return stable_fingerprint(
        "personal-pattern-review-v1",
        item.pattern_id,
        item.status,
        item.confidence,
        item.evidence_fingerprint,
        item.evidence_health,
        item.review_due,
        item.review_due_at or "",
        *(f"review-reason:{reason}" for reason in item.review_reasons),
        *(f"trigger:{part}" for part in trigger_parts),
        *(f"evidence:{part}" for part in _diagnostic_part(item)),
    )


def _source(item: PersonalModelItem, generated_at: str) -> tuple[ReviewSourceReference, ...]:
    return (
        ReviewSourceReference(
            path=item.pattern_path,
            content_hash=item.pattern_content_hash,
            detail="Canonical personal-pattern artifact.",
            observed_at=generated_at,
        ),
    )


def _trigger_codes(item: PersonalModelItem) -> frozenset[str]:
    return frozenset(reason.code for reason in item.review_trigger_reasons)


def _weekly_labels(item: PersonalModelItem) -> tuple[str, ...]:
    labels: list[str] = []
    codes = _trigger_codes(item)
    if item.status == "needs-review":
        labels.append("already marked needs review")
    if item.review_due:
        labels.append("review due")
    if item.status == "active" and codes & _MATERIAL_REVIEW_CODES:
        labels.append("evidence changed")
    if "new-counter-evidence" in codes:
        labels.append("contesting evidence changed")
    if item.status == "seed" and item.last_reviewed_at is None:
        labels.append("new seed")
    return tuple(dict.fromkeys(labels))


def _weekly_priority(item: PersonalModelItem) -> tuple[int, str]:
    labels = set(_weekly_labels(item))
    if "already marked needs review" in labels:
        priority = 0
    elif "review due" in labels:
        priority = 1
    elif "contesting evidence changed" in labels:
        priority = 2
    elif "evidence changed" in labels:
        priority = 3
    else:
        priority = 4
    return priority, item.pattern_id


def _review_item(
    item: PersonalModelItem,
    *,
    section_id: str,
    labels: Iterable[str],
    generated_at: str,
) -> ReviewItemSnapshot:
    reasons = tuple(labels)
    reason_text = ", ".join(reasons) if reasons else "explicitly selected"
    detail = (
        f"Optional pattern review: {reason_text}. Status {item.status}; "
        f"confidence {item.confidence}; evidence {item.evidence_health}."
    )
    return ReviewItemSnapshot(
        item_id=f"{_ITEM_PREFIX}{item.pattern_id}",
        section_id=section_id,
        title=item.title,
        detail=detail,
        evidence_fingerprint=pattern_review_fingerprint(item),
        state="ready",
        action="open-source",
        sources=_source(item, generated_at),
    )


def _unavailable(section_id: str, title: str, exc: Exception) -> ReviewSectionSnapshot:
    return ReviewSectionSnapshot(
        section_id,
        title,
        True,
        "unavailable",
        (),
        str(exc),
    )


def weekly_pattern_review_section(
    *, vault_root: Path, runtime_dir: Path, generated_at: datetime
) -> ReviewSectionSnapshot:
    """Return a small optional weekly set without surfacing every active pattern."""
    try:
        document = _review_model(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            generated_at=generated_at,
        )
    except (ToolExecutionError, PersonalModelError) as exc:
        return _unavailable(_WEEKLY_SECTION_ID, "Personal patterns", exc)

    candidates = [
        item
        for item in document.items
        if item.status != "archived" and _weekly_labels(item)
    ]
    candidates.sort(key=_weekly_priority)
    bounded = candidates[:WEEKLY_PATTERN_REVIEW_LIMIT]
    generated = generated_at.isoformat()
    items = tuple(
        _review_item(
            item,
            section_id=_WEEKLY_SECTION_ID,
            labels=_weekly_labels(item),
            generated_at=generated,
        )
        for item in bounded
    )
    return ReviewSectionSnapshot(
        _WEEKLY_SECTION_ID,
        "Personal patterns",
        True,
        "ready" if items else "empty",
        items,
    )


def daily_pattern_review_section(
    *,
    vault_root: Path,
    runtime_dir: Path,
    generated_at: datetime,
    urgent_pattern_ids: Iterable[str] = (),
    pinned_pattern_ids: Iterable[str] = (),
) -> ReviewSectionSnapshot:
    """Surface only explicitly urgent or pinned pattern IDs; default daily state is empty."""
    urgent = frozenset(urgent_pattern_ids)
    pinned = frozenset(pinned_pattern_ids)
    selected_ids = urgent | pinned
    if not selected_ids:
        return ReviewSectionSnapshot(_DAILY_SECTION_ID, "Personal patterns", True, "empty")

    try:
        document = _review_model(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            generated_at=generated_at,
        )
    except (ToolExecutionError, PersonalModelError) as exc:
        return _unavailable(_DAILY_SECTION_ID, "Personal patterns", exc)

    by_id = {
        item.pattern_id: item
        for item in document.items
        if item.status != "archived" and item.pattern_id in selected_ids
    }
    ordered_ids = sorted(selected_ids, key=lambda value: (value not in urgent, value))
    generated = generated_at.isoformat()
    items: list[ReviewItemSnapshot] = []
    for pattern_id in ordered_ids:
        item = by_id.get(pattern_id)
        if item is None:
            continue
        labels = []
        if pattern_id in urgent:
            labels.append("explicitly urgent")
        if pattern_id in pinned:
            labels.append("explicitly pinned")
        items.append(
            _review_item(
                item,
                section_id=_DAILY_SECTION_ID,
                labels=labels,
                generated_at=generated,
            )
        )
        if len(items) >= DAILY_PATTERN_REVIEW_LIMIT:
            break
    return ReviewSectionSnapshot(
        _DAILY_SECTION_ID,
        "Personal patterns",
        True,
        "ready" if items else "empty",
        tuple(items),
    )


def create_pattern_review_proposal(
    *,
    vault_root: Path,
    runtime_dir: Path,
    review: ReviewArtifact,
    item_id: str,
    evidence_fingerprint: str,
    actor_id: str,
    now: datetime,
) -> dict[str, object]:
    """Create a pattern needs-review draft from a still-current visible review item."""
    visible = artifact_item_fingerprints(review)
    if visible.get(item_id) != evidence_fingerprint:
        raise DailyInteractionError(
            "stale_review_item",
            "The personal-pattern review item no longer matches the review artifact.",
            "Refresh the review and propose from the current item.",
            {"item_id": item_id, "visible_fingerprint": visible.get(item_id)},
        )
    if not item_id.startswith(_ITEM_PREFIX):
        raise PatternError(
            "invalid_review_item",
            "The review item is not a personal-pattern item.",
            {"item_id": item_id},
        )
    pattern_id = item_id.removeprefix(_ITEM_PREFIX)
    document = _review_model(vault_root=vault_root, runtime_dir=runtime_dir, generated_at=now)
    current = next((item for item in document.items if item.pattern_id == pattern_id), None)
    if current is None or pattern_review_fingerprint(current) != evidence_fingerprint:
        raise DailyInteractionError(
            "stale_review_item",
            "The personal-pattern evidence changed after the review item was rendered.",
            "Refresh the review and propose from the current evidence.",
            {"item_id": item_id},
        )
    registry = Registry(runtime_dir / "registry.db")
    service = PatternReviewService(
        vault_root=vault_root,
        registry=registry,
        allow_path=_allow_all,
    )
    assessment = service.assess(pattern_id, now=now)
    return service.create_review_proposal(assessment, actor_id=actor_id, now=now)
