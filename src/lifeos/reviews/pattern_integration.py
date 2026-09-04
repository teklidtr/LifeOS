"""Pattern-aware adapters over the generic canonical review engine.

The generic review modules stay domain-neutral. This adapter adds the few Phase 17
semantics that need cross-review history, explicit daily attention transport, and
specialized personal-pattern proposal handoff.
"""

from __future__ import annotations

import json
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from lifeos.daily import content_hash
from lifeos.daily.errors import DailyInteractionError
from lifeos.patterns.reviews import (
    DAILY_PATTERN_REVIEW_LIMIT,
    WEEKLY_PATTERN_REVIEW_LIMIT,
    create_pattern_review_proposal,
    daily_pattern_review_section,
    push_pattern_review_model_cache,
    reset_pattern_review_model_cache,
    weekly_pattern_review_section,
)
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.contracts import (
    DecisionKind,
    ReviewArtifact,
    ReviewItemDecision,
    ReviewSectionSnapshot,
    ReviewSnapshot,
    ReviewSnapshotRecord,
)
from lifeos.reviews.decisions import ReviewDecisionService as _BaseReviewDecisionService
from lifeos.reviews.history import (
    ReviewContinuity,
    adjacent_reviews,
    apply_continuity_to_snapshot,
    build_review_continuity,
    list_review_history,
    render_review_continuity,
)
from lifeos.reviews.snapshot import (
    build_review_snapshot as _base_build_review_snapshot,
    render_snapshot_facts,
    render_snapshot_items,
)


@dataclass(frozen=True, slots=True)
class PatternReviewAttention:
    urgent_pattern_ids: tuple[str, ...] = ()
    pinned_pattern_ids: tuple[str, ...] = ()


_PATTERN_REVIEW_ATTENTION: ContextVar[PatternReviewAttention] = ContextVar(
    "lifeos_pattern_review_attention",
    default=PatternReviewAttention(),
)


def _stable_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def push_pattern_review_attention(
    *,
    urgent_pattern_ids: Iterable[str] = (),
    pinned_pattern_ids: Iterable[str] = (),
) -> Token[PatternReviewAttention]:
    """Temporarily carry explicit workspace attention through the strict bridge."""
    return _PATTERN_REVIEW_ATTENTION.set(
        PatternReviewAttention(
            _stable_ids(urgent_pattern_ids),
            _stable_ids(pinned_pattern_ids),
        )
    )


def reset_pattern_review_attention(token: Token[PatternReviewAttention]) -> None:
    _PATTERN_REVIEW_ATTENTION.reset(token)


def resolve_pattern_review_attention(
    *,
    urgent_pattern_ids: Iterable[str] = (),
    pinned_pattern_ids: Iterable[str] = (),
) -> PatternReviewAttention:
    """Prefer explicit function arguments, otherwise use the bridge-scoped context."""
    urgent = _stable_ids(urgent_pattern_ids)
    pinned = _stable_ids(pinned_pattern_ids)
    if urgent or pinned:
        return PatternReviewAttention(urgent, pinned)
    return _PATTERN_REVIEW_ATTENTION.get()


def _rehash_snapshot(
    snapshot: ReviewSnapshot,
    sections: tuple[ReviewSectionSnapshot, ...],
    *,
    continuity: ReviewContinuity | None = None,
) -> ReviewSnapshot:
    payload: dict[str, object] = {
        "generated_at": snapshot.generated_at,
        "sections": [asdict(section) for section in sections],
        "diagnostics": snapshot.diagnostics,
    }
    if continuity is not None:
        payload["continuity"] = continuity.to_dict()
    digest = "sha256:" + content_hash(json.dumps(payload, sort_keys=True, default=str))
    return ReviewSnapshot(
        f"{snapshot.snapshot_id.rsplit(':', 1)[0]}:{digest[-16:]}",
        snapshot.generated_at,
        digest,
        sections,
        snapshot.diagnostics,
    )


def _replace_section(
    snapshot: ReviewSnapshot,
    replacement: ReviewSectionSnapshot,
) -> ReviewSnapshot:
    sections = tuple(
        replacement if section.section_id == replacement.section_id else section
        for section in snapshot.sections
    )
    if sections == snapshot.sections:
        return snapshot
    return _rehash_snapshot(snapshot, sections)


def _bound_pattern_sections(
    snapshot: ReviewSnapshot, continuity: ReviewContinuity
) -> ReviewSnapshot:
    changed = False
    bounded: list[ReviewSectionSnapshot] = []
    for section in snapshot.sections:
        limit = None
        if section.section_id == "personal-patterns-weekly":
            limit = WEEKLY_PATTERN_REVIEW_LIMIT
        elif section.section_id == "personal-patterns-daily":
            limit = DAILY_PATTERN_REVIEW_LIMIT
        if limit is None or len(section.items) <= limit:
            bounded.append(section)
            continue
        changed = True
        items = section.items[:limit]
        bounded.append(replace(section, items=items, state="ready" if items else "empty"))
    if not changed:
        return snapshot
    return _rehash_snapshot(snapshot, tuple(bounded), continuity=continuity)


def build_review_snapshot(
    *,
    vault_root: Path,
    runtime_dir: Path,
    kind: str,
    day: date,
    generated_at: datetime,
    urgent_pattern_ids: tuple[str, ...] = (),
    pinned_pattern_ids: tuple[str, ...] = (),
    enforce_pattern_limits: bool = True,
) -> ReviewSnapshot:
    """Build the ordinary snapshot, optionally exposing all pattern candidates internally."""
    attention = resolve_pattern_review_attention(
        urgent_pattern_ids=urgent_pattern_ids,
        pinned_pattern_ids=pinned_pattern_ids,
    )
    if kind != "daily" and (attention.urgent_pattern_ids or attention.pinned_pattern_ids):
        raise ValueError("Explicit pattern attention is supported only for daily reviews.")

    cache_token = push_pattern_review_model_cache() if not enforce_pattern_limits else None
    try:
        snapshot = _base_build_review_snapshot(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            kind=kind,
            day=day,
            generated_at=generated_at,
            urgent_pattern_ids=attention.urgent_pattern_ids,
            pinned_pattern_ids=attention.pinned_pattern_ids,
        )
        if enforce_pattern_limits:
            return snapshot
        if kind == "daily":
            replacement = daily_pattern_review_section(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
                generated_at=generated_at,
                urgent_pattern_ids=attention.urgent_pattern_ids,
                pinned_pattern_ids=attention.pinned_pattern_ids,
                limit=None,
            )
        else:
            replacement = weekly_pattern_review_section(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
                generated_at=generated_at,
                limit=None,
            )
        return _replace_section(snapshot, replacement)
    finally:
        if cache_token is not None:
            reset_pattern_review_model_cache(cache_token)


def _effective_previous(
    *,
    service: ReviewArtifactService,
    artifact: ReviewArtifact,
) -> ReviewArtifact | None:
    """Return the immediate previous review carrying the latest prior decision per item.

    Review identity/path still points at the adjacent artifact. Only the disposable
    in-memory decision view is widened across older same-kind reviews so an unchanged
    dismissal remains effective until a later decision or fingerprint change supersedes it.
    """
    previous, _ = adjacent_reviews(service=service, artifact=artifact)
    if previous is None:
        return None
    current_key = (artifact.metadata.period_start.isoformat(), artifact.metadata.review_id)
    latest: dict[str, ReviewItemDecision] = {}
    for entry in list_review_history(service=service, kind=artifact.metadata.review_kind):
        if (entry.period_start, entry.review_id) >= current_key:
            continue
        prior = service.load_id(entry.review_id)
        for decision in sorted(
            prior.metadata.item_decisions,
            key=lambda item: item.decided_at,
            reverse=True,
        ):
            latest.setdefault(decision.item_id, decision)
    decisions = tuple(
        sorted(
            latest.values(),
            key=lambda item: (item.item_id, item.evidence_fingerprint),
        )
    )
    return replace(previous, metadata=replace(previous.metadata, item_decisions=decisions))


def refresh_review_snapshot(
    *,
    service: ReviewArtifactService,
    artifact: ReviewArtifact,
    runtime_dir: Path,
    generated_at: datetime,
    idempotency_key: str,
    urgent_pattern_ids: tuple[str, ...] = (),
    pinned_pattern_ids: tuple[str, ...] = (),
) -> tuple[ReviewArtifact, ReviewSnapshot]:
    """Refresh with historical dismissal continuity before enforcing pattern bounds."""
    attention = resolve_pattern_review_attention(
        urgent_pattern_ids=urgent_pattern_ids,
        pinned_pattern_ids=pinned_pattern_ids,
    )
    if artifact.metadata.review_kind != "daily" and (
        attention.urgent_pattern_ids or attention.pinned_pattern_ids
    ):
        raise ValueError("Explicit pattern attention is supported only for daily reviews.")
    snapshot = build_review_snapshot(
        vault_root=service.vault_root,
        runtime_dir=runtime_dir,
        kind=artifact.metadata.review_kind,
        day=artifact.metadata.period_start,
        generated_at=generated_at,
        urgent_pattern_ids=attention.urgent_pattern_ids,
        pinned_pattern_ids=attention.pinned_pattern_ids,
        enforce_pattern_limits=False,
    )
    previous = _effective_previous(service=service, artifact=artifact)
    continuity = build_review_continuity(current_snapshot=snapshot, previous=previous)
    snapshot = apply_continuity_to_snapshot(snapshot, continuity)
    snapshot = _bound_pattern_sections(snapshot, continuity)

    history = artifact.metadata.snapshot_history
    record = ReviewSnapshotRecord(
        snapshot.snapshot_id, snapshot.content_hash, snapshot.generated_at
    )
    if not history or history[-1].snapshot_id != record.snapshot_id:
        history = (*history, record)[-20:]
    updated = service.update(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key=idempotency_key,
        now=generated_at,
        update=ReviewArtifactUpdate(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.content_hash,
            snapshot_history=history,
            previous_review_id=continuity.previous_review_id,
            managed_blocks={
                "facts": render_snapshot_facts(snapshot),
                "items": render_snapshot_items(snapshot),
                "continuity": render_review_continuity(continuity),
            },
        ),
    )
    return updated, snapshot


class ReviewDecisionService(_BaseReviewDecisionService):
    """Generic review decisions plus explicit personal-pattern proposal handoff."""

    def decide(
        self,
        *,
        review_id: str,
        item_id: str,
        evidence_fingerprint: str,
        decision: DecisionKind,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
        note: str | None = None,
        proposal_id: str | None = None,
    ) -> ReviewArtifact:
        if decision == "propose_change" and not proposal_id and item_id.startswith(
            "personal-pattern:"
        ):
            artifact = self.artifacts.load_id(review_id)
            existing = next(
                (
                    item
                    for item in artifact.metadata.item_decisions
                    if item.item_id == item_id
                    and item.evidence_fingerprint == evidence_fingerprint
                    and item.decision == "propose_change"
                    and item.proposal_id
                ),
                None,
            )
            if existing is not None:
                proposal_id = existing.proposal_id
            else:
                if artifact.content_hash != expected_hash:
                    raise DailyInteractionError(
                        "stale_write",
                        "The review changed after it was opened.",
                        "Reload the review and preserve newer Markdown edits.",
                        {"actual_hash": artifact.content_hash, "path": artifact.path},
                    )
                result = create_pattern_review_proposal(
                    vault_root=self.artifacts.vault_root,
                    runtime_dir=self.artifacts.runtime_dir,
                    review=artifact,
                    item_id=item_id,
                    evidence_fingerprint=evidence_fingerprint,
                    actor_id=self.artifacts.actor_id,
                    now=now,
                )
                proposal_id = str(result["proposal_id"])
        return super().decide(
            review_id=review_id,
            item_id=item_id,
            evidence_fingerprint=evidence_fingerprint,
            decision=decision,
            expected_hash=expected_hash,
            idempotency_key=idempotency_key,
            now=now,
            note=note,
            proposal_id=proposal_id,
        )
