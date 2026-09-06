"""Review history, continuity, carry-forward, and suppression rules."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Literal

from lifeos.daily import content_hash
from lifeos.daily.errors import DailyInteractionError
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.contracts import ReviewArtifact, ReviewSectionSnapshot, ReviewSnapshot
from lifeos.vault import VaultAccessError, iter_vault_markdown

ContinuityState = Literal[
    "carried", "unresolved", "suppressed", "evidence_changed", "no_longer_present"
]


@dataclass(frozen=True, slots=True)
class ReviewHistoryEntry:
    review_id: str
    path: str
    review_kind: str
    period_start: str
    period_end: str
    status: str
    updated_at: str
    phase_states: tuple[tuple[str, str], ...]
    proposal_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewContinuityItem:
    item_id: str
    previous_review_id: str
    previous_fingerprint: str
    current_fingerprint: str | None
    decision: str
    state: ContinuityState
    note: str | None = None
    proposal_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewContinuity:
    previous_review_id: str | None
    previous_path: str | None
    previous_status: str | None
    items: tuple[ReviewContinuityItem, ...]
    suppressed_item_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def list_review_history(
    *,
    service: ReviewArtifactService,
    kind: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> tuple[ReviewHistoryEntry, ...]:
    rows: list[ReviewHistoryEntry] = []
    try:
        sources = iter_vault_markdown(service.vault_root, roots=("reviews",))
    except VaultAccessError as exc:
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check vault access and retry."
        ) from exc
    for source in sources:
        if not source.relative_path.startswith(("reviews/daily/", "reviews/weekly/")):
            continue
        try:
            artifact = service.load_path(source.relative_path)
        except DailyInteractionError:
            continue
        metadata = artifact.metadata
        if kind and metadata.review_kind != kind:
            continue
        if status and metadata.status != status:
            continue
        rows.append(
            ReviewHistoryEntry(
                metadata.review_id,
                artifact.path,
                metadata.review_kind,
                metadata.period_start.isoformat(),
                metadata.period_end.isoformat(),
                metadata.status,
                metadata.updated_at,
                tuple((phase.phase_id, phase.state) for phase in metadata.phases),
                metadata.proposal_refs,
            )
        )
    rows.sort(key=lambda row: (row.period_start, row.review_id), reverse=True)
    return tuple(rows[:limit] if limit is not None else rows)


def adjacent_reviews(
    *, service: ReviewArtifactService, artifact: ReviewArtifact
) -> tuple[ReviewArtifact | None, ReviewArtifact | None]:
    entries = list_review_history(service=service, kind=artifact.metadata.review_kind)
    ascending = sorted(entries, key=lambda row: (row.period_start, row.review_id))
    index = next(
        (i for i, row in enumerate(ascending) if row.review_id == artifact.metadata.review_id), None
    )
    if index is None:
        return None, None
    previous = service.load_id(ascending[index - 1].review_id) if index > 0 else None
    following = (
        service.load_id(ascending[index + 1].review_id) if index + 1 < len(ascending) else None
    )
    return previous, following


def build_review_continuity(
    *, current_snapshot: ReviewSnapshot, previous: ReviewArtifact | None
) -> ReviewContinuity:
    if previous is None:
        return ReviewContinuity(None, None, None, (), ())
    current_items = {
        item.item_id: item for section in current_snapshot.sections for item in section.items
    }
    continuity: list[ReviewContinuityItem] = []
    suppressed: set[str] = set()
    for decision in previous.metadata.item_decisions:
        current = current_items.get(decision.item_id)
        current_fingerprint = current.evidence_fingerprint if current else None
        if decision.decision == "dismiss_for_review":
            if current_fingerprint == decision.evidence_fingerprint:
                state: ContinuityState = "suppressed"
                suppressed.add(decision.item_id)
            elif current_fingerprint is None:
                state = "no_longer_present"
            else:
                state = "evidence_changed"
        elif decision.decision == "carry":
            state = (
                "carried"
                if current_fingerprint == decision.evidence_fingerprint
                else ("no_longer_present" if current_fingerprint is None else "evidence_changed")
            )
        elif decision.decision in {"defer_review", "clarify", "propose_change"}:
            state = (
                "unresolved"
                if current_fingerprint == decision.evidence_fingerprint
                else ("no_longer_present" if current_fingerprint is None else "evidence_changed")
            )
        else:
            continue
        continuity.append(
            ReviewContinuityItem(
                decision.item_id,
                previous.metadata.review_id,
                decision.evidence_fingerprint,
                current_fingerprint,
                decision.decision,
                state,
                decision.note,
                decision.proposal_id,
            )
        )
    continuity.sort(key=lambda item: (item.state, item.item_id))
    return ReviewContinuity(
        previous.metadata.review_id,
        previous.path,
        previous.metadata.status,
        tuple(continuity),
        tuple(sorted(suppressed)),
    )


def apply_continuity_to_snapshot(
    snapshot: ReviewSnapshot, continuity: ReviewContinuity
) -> ReviewSnapshot:
    suppressed = set(continuity.suppressed_item_ids)
    if not suppressed:
        return snapshot
    sections: list[ReviewSectionSnapshot] = []
    for section in snapshot.sections:
        items = tuple(item for item in section.items if item.item_id not in suppressed)
        sections.append(
            replace(
                section,
                items=items,
                state="empty" if not items and section.state == "ready" else section.state,
            )
        )
    payload = {
        "generated_at": snapshot.generated_at,
        "sections": [asdict(section) for section in sections],
        "diagnostics": snapshot.diagnostics,
        "continuity": continuity.to_dict(),
    }
    digest = "sha256:" + content_hash(json.dumps(payload, sort_keys=True, default=str))
    return ReviewSnapshot(
        f"{snapshot.snapshot_id.rsplit(':', 1)[0]}:{digest[-16:]}",
        snapshot.generated_at,
        digest,
        tuple(sections),
        snapshot.diagnostics,
    )


def render_review_continuity(continuity: ReviewContinuity) -> str:
    lines = ["## Continuity", ""]
    if continuity.previous_review_id is None:
        return "\n".join((*lines, "No previous review is linked yet."))
    lines.append(
        f"Previous review: [{continuity.previous_review_id}]({continuity.previous_path})"
        f" ({continuity.previous_status})."
    )
    lines.append("")
    visible = [item for item in continuity.items if item.state != "suppressed"]
    if not visible:
        lines.append("No prior decision requires attention in this review.")
    else:
        lines.append("### Prior decisions")
        for item in visible:
            suffix = f" Proposal: `{item.proposal_id}`." if item.proposal_id else ""
            note = f" Note: {item.note}" if item.note else ""
            lines.append(
                f"- `{item.item_id}`: **{item.state.replace('_', ' ')}** after "
                f"`{item.decision}`.{suffix}{note}"
            )
    if continuity.suppressed_item_ids:
        lines.extend(
            [
                "",
                "### Suppressed unchanged items",
                *[
                    f"- `{item_id}` remains dismissed because its evidence fingerprint is unchanged."
                    for item_id in continuity.suppressed_item_ids
                ],
            ]
        )
    return "\n".join(lines).rstrip()


def link_review_history(
    *,
    service: ReviewArtifactService,
    artifact: ReviewArtifact,
    now: datetime,
    idempotency_key: str,
) -> ReviewArtifact:
    previous, following = adjacent_reviews(service=service, artifact=artifact)
    current = artifact
    if previous and previous.metadata.next_review_id != artifact.metadata.review_id:
        service.update(
            review_id=previous.metadata.review_id,
            expected_hash=previous.content_hash,
            idempotency_key=f"{idempotency_key}-previous",
            now=now,
            update=ReviewArtifactUpdate(next_review_id=artifact.metadata.review_id),
        )
    previous_id = previous.metadata.review_id if previous else None
    following_id = following.metadata.review_id if following else None
    if (
        current.metadata.previous_review_id != previous_id
        or current.metadata.next_review_id != following_id
    ):
        current = service.update(
            review_id=current.metadata.review_id,
            expected_hash=current.content_hash,
            idempotency_key=f"{idempotency_key}-current",
            now=now,
            update=ReviewArtifactUpdate(
                previous_review_id=previous_id, next_review_id=following_id
            ),
        )
    if following and following.metadata.previous_review_id != artifact.metadata.review_id:
        service.update(
            review_id=following.metadata.review_id,
            expected_hash=following.content_hash,
            idempotency_key=f"{idempotency_key}-following",
            now=now,
            update=ReviewArtifactUpdate(previous_review_id=artifact.metadata.review_id),
        )
    return current
