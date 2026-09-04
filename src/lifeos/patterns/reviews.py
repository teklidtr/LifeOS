"""Bounded personal-pattern evidence for canonical daily and weekly reviews."""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

from lifeos.daily.errors import DailyInteractionError
from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.registry_tools import refresh_registry
from lifeos.registry import Registry
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy

from .contracts import PatternError
from .model import (
    PersonalModelDocument,
    PersonalModelError,
    PersonalModelItem,
    build_personal_model_document,
)
from .proposals import MarkPatternNeedsReviewRequest, PatternProposalService

if TYPE_CHECKING:
    from lifeos.reviews.contracts import (
        ReviewArtifact,
        ReviewItemSnapshot,
        ReviewSectionSnapshot,
        ReviewSourceReference,
    )

WEEKLY_PATTERN_REVIEW_LIMIT = 8
DAILY_PATTERN_REVIEW_LIMIT = 3
PATTERN_REVIEW_EVIDENCE_SOURCE_LIMIT = 3

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
_ReviewModelCache = dict[tuple[str, str, str], PersonalModelDocument]
_REVIEW_MODEL_CACHE: ContextVar[_ReviewModelCache | None] = ContextVar(
    "lifeos_pattern_review_model_cache",
    default=None,
)


def push_pattern_review_model_cache() -> Token[_ReviewModelCache | None]:
    """Cache one scoped Personal Model inside a single higher-level review refresh."""
    return _REVIEW_MODEL_CACHE.set({})


def reset_pattern_review_model_cache(token: Token[_ReviewModelCache | None]) -> None:
    _REVIEW_MODEL_CACHE.reset(token)


def _review_allow_path(vault_root: Path) -> Callable[[str], bool]:
    """Build the ordinary local review scope before any review evidence is opened."""
    try:
        policy = load_retrieval_policy(vault_root)
    except RetrievalError as exc:
        raise PersonalModelError(f"Could not load retrieval policy for pattern review: {exc}") from exc
    scope = RetrievalScope()

    def allowed(path: str) -> bool:
        try:
            return scope_decision(path, scope=scope, policy=policy, mode="local").allowed
        except RetrievalError:
            # Scanner and canonical artifact paths should already be valid, but a
            # malformed path at this boundary must fail closed rather than widening scope.
            return False

    return allowed


def _review_model(
    *, vault_root: Path, runtime_dir: Path, generated_at: datetime
) -> PersonalModelDocument:
    key = (str(vault_root), str(runtime_dir), generated_at.isoformat())
    cache = _REVIEW_MODEL_CACHE.get()
    if cache is not None and key in cache:
        return cache[key]

    registry = Registry(runtime_dir / "registry.db")
    allow_path = _review_allow_path(vault_root)
    # Pattern review depends on current file identity and content hashes. Refresh only
    # deterministic file facts inside the ordinary retrieval scope; denied paths remain
    # presence-only observations and their bytes are never opened by this review pass.
    refresh_registry(
        vault_root=vault_root,
        registry=registry,
        identity_allow_path=allow_path,
    )
    document = build_personal_model_document(
        vault_root=vault_root,
        registry=registry,
        allow_path=allow_path,
        now=generated_at,
    )
    if cache is not None:
        cache[key] = document
    return document


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
    from lifeos.reviews.contracts import stable_fingerprint

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
    from lifeos.reviews.contracts import ReviewSourceReference

    sources = [
        ReviewSourceReference(
            path=item.pattern_path,
            content_hash=item.pattern_content_hash,
            detail="Canonical personal-pattern artifact.",
            observed_at=generated_at,
        )
    ]
    for diagnostic in item.evidence_diagnostics[:PATTERN_REVIEW_EVIDENCE_SOURCE_LIMIT]:
        sources.append(
            ReviewSourceReference(
                path=diagnostic.current_path or diagnostic.reference.path,
                content_hash=diagnostic.current_content_hash or diagnostic.reference.content_hash,
                detail=(
                    f"{diagnostic.reference.role.title()} evidence; current state "
                    f"{diagnostic.state}."
                ),
                observed_at=generated_at,
            )
        )
    return tuple(sources)


def _trigger_codes(item: PersonalModelItem) -> frozenset[str]:
    return frozenset(reason.code for reason in item.review_trigger_reasons)


def _weekly_labels(item: PersonalModelItem) -> tuple[str, ...]:
    labels: list[str] = []
    codes = _trigger_codes(item)
    if item.status == "needs-review":
        labels.append("already marked needs review")
    if item.review_due:
        labels.append("review due")
    if any(reference.role == "contesting" for reference in item.evidence):
        labels.append("unresolved contesting evidence")
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
    elif labels & {"unresolved contesting evidence", "contesting evidence changed"}:
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
    from lifeos.reviews.contracts import ReviewItemSnapshot

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
    from lifeos.reviews.contracts import ReviewSectionSnapshot

    return ReviewSectionSnapshot(
        section_id,
        title,
        True,
        "unavailable",
        (),
        str(exc),
    )


def weekly_pattern_review_section(
    *,
    vault_root: Path,
    runtime_dir: Path,
    generated_at: datetime,
    limit: int | None = WEEKLY_PATTERN_REVIEW_LIMIT,
) -> ReviewSectionSnapshot:
    """Return a small optional weekly set without surfacing every active pattern.

    ``limit=None`` is reserved for the refresh pipeline so continuity suppression can
    run before the public section bound is enforced. Ordinary callers retain the
    documented eight-item limit.
    """
    from lifeos.reviews.contracts import ReviewSectionSnapshot

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("weekly pattern review limit must be positive or None")
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
    bounded = candidates if limit is None else candidates[:limit]
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
    limit: int | None = DAILY_PATTERN_REVIEW_LIMIT,
) -> ReviewSectionSnapshot:
    """Surface only explicitly urgent or pinned pattern IDs; default daily state is empty.

    ``limit=None`` is reserved for refresh so previously dismissed items can be
    suppressed before the documented three-item daily bound is applied.
    """
    from lifeos.reviews.contracts import ReviewSectionSnapshot

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("daily pattern review limit must be positive or None")
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
        if limit is not None and len(items) >= limit:
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
    from lifeos.reviews.decisions import artifact_item_fingerprints

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
    if current.status == "needs-review":
        raise PatternError(
            "invalid_transition",
            "The pattern is already marked needs-review; revise or resolve the existing review instead.",
            {"pattern_id": pattern_id},
        )
    review_reasons = _weekly_labels(current) or (
        "Explicitly proposed from a personal-pattern review item.",
    )
    transition_reason = (
        "User explicitly proposed marking this pattern needs-review from canonical review "
        f"{review.metadata.review_id}."
    )
    return PatternProposalService(vault_root=vault_root, actor_id=actor_id).publish(
        MarkPatternNeedsReviewRequest(
            target_path=current.pattern_path,
            transition_reason=transition_reason,
            review_reasons=review_reasons,
        ),
        now=now,
    )
