"""Canonical Markdown storage for first-class review artifacts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import _atomic_write, content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.reviews.contracts import (
    REVIEW_SCHEMA_VERSION,
    ReviewAnswer,
    ReviewArtifact,
    ReviewArtifactMetadata,
    ReviewItemDecision,
    ReviewLifecycleEvent,
    ReviewPhaseProgress,
    ReviewStatus,
    ReviewSnapshotRecord,
    default_phases,
    review_identity,
    review_path,
    validate_review_metadata,
)
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

_MANAGED_NAMES = ("facts", "items", "continuity", "completion-summary")
_REVIEW_ID = re.compile(r"^(daily-(\d{4}-\d{2}-\d{2})|weekly-(\d{4}-W\d{2}))$")


@dataclass(frozen=True, slots=True)
class ReviewArtifactUpdate:
    status: ReviewStatus | None = None
    current_phase: str | None = None
    phases: tuple[ReviewPhaseProgress, ...] | None = None
    item_decisions: tuple[ReviewItemDecision, ...] | None = None
    answers: tuple[ReviewAnswer, ...] | None = None
    proposal_refs: tuple[str, ...] | None = None
    previous_review_id: str | None = None
    next_review_id: str | None = None
    migrated_from: tuple[str, ...] | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    snapshot_history: tuple[ReviewSnapshotRecord, ...] | None = None
    lifecycle_events: tuple[ReviewLifecycleEvent, ...] | None = None
    managed_blocks: Mapping[str, str] | None = None

    def fingerprint_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["managed_blocks"] = dict(sorted((self.managed_blocks or {}).items()))
        return payload


def _frontmatter_document(frontmatter: Mapping[str, Any], body: str) -> str:
    dumped = yaml.safe_dump(dict(frontmatter), sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{dumped}\n---\n\n{body.lstrip()}".rstrip() + "\n"


def _metadata_frontmatter(metadata: ReviewArtifactMetadata) -> dict[str, Any]:
    return {
        "type": "review",
        "review_schema": metadata.schema_version,
        "review_id": metadata.review_id,
        "review_kind": metadata.review_kind,
        "period_start": metadata.period_start,
        "period_end": metadata.period_end,
        "timezone": metadata.timezone,
        "status": metadata.status,
        "created_at": metadata.created_at,
        "updated_at": metadata.updated_at,
        "phases": [phase.to_dict() for phase in metadata.phases],
        "current_phase": metadata.current_phase,
        "item_decisions": [decision.to_dict() for decision in metadata.item_decisions],
        "answers": [answer.to_dict() for answer in metadata.answers],
        "proposal_refs": list(metadata.proposal_refs),
        "previous_review_id": metadata.previous_review_id,
        "next_review_id": metadata.next_review_id,
        "migrated_from": list(metadata.migrated_from),
        "snapshot_id": metadata.snapshot_id,
        "snapshot_hash": metadata.snapshot_hash,
        "snapshot_history": [record.to_dict() for record in metadata.snapshot_history],
        "lifecycle_events": [event.to_dict() for event in metadata.lifecycle_events],
    }


def _managed_block(name: str, content: str) -> str:
    if name not in _MANAGED_NAMES:
        raise DailyInteractionError(
            "invalid_managed_block",
            f"Unsupported review managed block: {name}",
            "Use one of the documented review block names.",
        )
    return (
        f"<!-- lifeos:managed:start {name} -->\n"
        f"{content.rstrip()}\n"
        f"<!-- lifeos:managed:end {name} -->"
    )


def _block_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"<!-- lifeos:managed:start {re.escape(name)} -->.*?"
        rf"<!-- lifeos:managed:end {re.escape(name)} -->",
        re.S,
    )


def validate_managed_blocks(body: str) -> None:
    for name in _MANAGED_NAMES:
        count = len(_block_pattern(name).findall(body))
        if count != 1:
            raise DailyInteractionError(
                "invalid_review_artifact",
                f"Review managed block '{name}' must appear exactly once; found {count}.",
                "Restore the managed boundary before refreshing or updating the review.",
                {"block": name, "count": count},
            )


def replace_managed_blocks(body: str, updates: Mapping[str, str]) -> str:
    validate_managed_blocks(body)
    result = body
    for name, content in sorted(updates.items()):
        if name not in _MANAGED_NAMES:
            raise DailyInteractionError(
                "invalid_managed_block",
                f"Unsupported review managed block: {name}",
                "Use one of the documented review block names.",
            )
        result = _block_pattern(name).sub(_managed_block(name, content), result, count=1)
    return result


def extract_managed_block(body: str, name: str) -> str:
    validate_managed_blocks(body)
    match = _block_pattern(name).search(body)
    assert match is not None
    text = match.group(0)
    start = f"<!-- lifeos:managed:start {name} -->\n"
    end = f"\n<!-- lifeos:managed:end {name} -->"
    return text.removeprefix(start).removesuffix(end)


def _initial_body(metadata: ReviewArtifactMetadata) -> str:
    label = (
        metadata.period_start.isoformat()
        if metadata.review_kind == "daily"
        else metadata.review_id.removeprefix("weekly-")
    )
    title = f"# {'Daily' if metadata.review_kind == 'daily' else 'Weekly'} review: {label}"
    blocks = [
        _managed_block("facts", "## Review facts\n\nFacts have not been refreshed yet."),
        _managed_block("items", "## Review items\n\nNo review snapshot has been generated yet."),
        _managed_block("continuity", "## Continuity\n\nNo previous review is linked yet."),
    ]
    if metadata.review_kind == "daily":
        human = """## Morning reflection

### Orientation


## Evening reflection

### Reconciliation


## Notes
"""
    else:
        human = """## Weekly reflection

### Themes and observations


### What changed


### Next orientation


## Notes
"""
    blocks.append(human.rstrip())
    blocks.append(_managed_block("completion-summary", "## Completion summary\n\nReview is open."))
    return f"{title}\n\n" + "\n\n".join(blocks) + "\n"


def _review_path_from_id(review_id: str) -> str:
    match = _REVIEW_ID.fullmatch(review_id)
    if match is None:
        raise DailyInteractionError(
            "invalid_review_id", "Review ID is invalid.", "Reload the review and choose a valid artifact."
        )
    if review_id.startswith("daily-"):
        return f"reviews/daily/{review_id.removeprefix('daily-')}.md"
    return f"reviews/weekly/{review_id.removeprefix('weekly-')}.md"


class ReviewArtifactService:
    """Create and update review notes while preserving human-owned Markdown."""

    def __init__(self, *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user") -> None:
        self.vault_root = vault_root
        self.runtime_dir = runtime_dir
        self.actor_id = actor_id
        self._idempotency_path = runtime_dir / "reviews" / "artifact-idempotency.json"

    def _check_duplicate_identity(self, review_id: str, expected_path: str) -> None:
        try:
            for source in iter_vault_markdown(self.vault_root, roots=("reviews",)):
                if source.relative_path == expected_path:
                    continue
                parsed = parse_markdown_note(source.path, content=source.content)
                if parsed.frontmatter.get("review_id") == review_id:
                    raise DailyInteractionError(
                        "duplicate_review_identity",
                        f"Review ID {review_id} already exists at {source.relative_path}.",
                        "Resolve the duplicate before creating or updating this review.",
                        {"review_id": review_id, "path": source.relative_path},
                    )
        except VaultAccessError as exc:
            raise DailyInteractionError(
                "storage_unavailable", str(exc), "Check vault access and retry."
            ) from exc

    def _idempotent(self, key: str, operation: str, payload: Mapping[str, Any], run: Any) -> ReviewArtifact:
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", key):
            raise DailyInteractionError(
                "invalid_idempotency_key",
                "Idempotency key is invalid.",
                "Use lowercase letters, digits, dot, underscore, or hyphen.",
            )
        fingerprint = content_hash(json.dumps(payload, sort_keys=True, default=str))
        self._idempotency_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            cache = (
                json.loads(self._idempotency_path.read_text(encoding="utf-8"))
                if self._idempotency_path.exists()
                else {}
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise DailyInteractionError(
                "review_runtime_corrupt",
                "Review idempotency state is corrupt.",
                "Remove the disposable review runtime cache and retry.",
            ) from exc
        previous = cache.get(key)
        if previous is not None:
            if previous.get("operation") != operation or previous.get("fingerprint") != fingerprint:
                raise DailyInteractionError(
                    "idempotency_conflict",
                    "The idempotency key was already used for a different review mutation.",
                    "Retry with a new idempotency key.",
                )
            return self.load_path(str(previous["path"]))
        result = run()
        cache[key] = {"operation": operation, "fingerprint": fingerprint, "path": result.path}
        temp = self._idempotency_path.with_suffix(".tmp")
        temp.write_text(json.dumps(cache, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, self._idempotency_path)
        return result

    def load(self, *, kind: str, day: date) -> ReviewArtifact:
        if kind not in {"daily", "weekly"}:
            raise DailyInteractionError(
                "invalid_review_kind", f"Unsupported review kind: {kind}", "Choose daily or weekly."
            )
        return self.load_path(review_path(kind, day))  # type: ignore[arg-type]

    def load_id(self, review_id: str) -> ReviewArtifact:
        return self.load_path(_review_path_from_id(review_id))

    def load_path(self, path: str) -> ReviewArtifact:
        try:
            source = read_vault_markdown(self.vault_root, path)
        except VaultAccessError as exc:
            code = "review_not_found" if exc.code == "not-found" else "storage_unavailable"
            raise DailyInteractionError(
                code,
                f"Review artifact could not be loaded: {path}",
                "Create or reopen the review, or check vault access.",
            ) from exc
        parsed = parse_markdown_note(source.path, content=source.content)
        error = next((finding for finding in parsed.findings if finding.severity == "error"), None)
        if error is not None:
            raise DailyInteractionError(
                "invalid_review_artifact", error.message, "Repair the Markdown note before continuing."
            )
        try:
            metadata = validate_review_metadata(dict(parsed.frontmatter), path=source.relative_path)
        except ValueError as exc:
            code = getattr(exc, "code", "invalid_review_artifact")
            raise DailyInteractionError(
                code,
                str(exc),
                "Repair or migrate the review artifact before continuing.",
            ) from exc
        validate_managed_blocks(parsed.body)
        return ReviewArtifact(source.relative_path, content_hash(source.content), metadata, parsed.body)

    def open_or_create(
        self,
        *,
        kind: str,
        day: date,
        timezone: str,
        now: datetime,
        idempotency_key: str,
    ) -> ReviewArtifact:
        if now.tzinfo is None:
            raise DailyInteractionError(
                "invalid_datetime", "Review timestamps must include a timezone.", "Use an aware datetime."
            )
        if kind not in {"daily", "weekly"}:
            raise DailyInteractionError(
                "invalid_review_kind", f"Unsupported review kind: {kind}", "Choose daily or weekly."
            )
        path = review_path(kind, day)  # type: ignore[arg-type]
        target = self.vault_root / path
        if target.exists():
            return self.load_path(path)
        review_id, start, end = review_identity(kind, day)  # type: ignore[arg-type]
        payload = {
            "kind": kind,
            "day": day.isoformat(),
            "timezone": timezone,
            "now": now.isoformat(),
        }

        def create() -> ReviewArtifact:
            self._check_duplicate_identity(review_id, path)
            timestamp = now.isoformat()
            metadata = ReviewArtifactMetadata(
                review_id=review_id,
                schema_version=REVIEW_SCHEMA_VERSION,
                review_kind=kind,  # type: ignore[arg-type]
                period_start=start,
                period_end=end,
                timezone=timezone,
                status="open",
                created_at=timestamp,
                updated_at=timestamp,
                phases=default_phases(kind),  # type: ignore[arg-type]
                current_phase="morning" if kind == "daily" else "weekly",
            )
            document = _frontmatter_document(_metadata_frontmatter(metadata), _initial_body(metadata))
            _atomic_write(self.vault_root, path, document, expected_hash=None, create=True)
            return self.load_path(path)

        return self._idempotent(idempotency_key, "review.open", payload, create)

    def update(
        self,
        *,
        review_id: str,
        expected_hash: str,
        idempotency_key: str,
        now: datetime,
        update: ReviewArtifactUpdate,
    ) -> ReviewArtifact:
        if now.tzinfo is None:
            raise DailyInteractionError(
                "invalid_datetime", "Review timestamps must include a timezone.", "Use an aware datetime."
            )
        payload = {
            "review_id": review_id,
            "expected_hash": expected_hash,
            "now": now.isoformat(),
            "update": update.fingerprint_payload(),
        }

        def apply() -> ReviewArtifact:
            current = self.load_id(review_id)
            if current.content_hash != expected_hash:
                raise DailyInteractionError(
                    "stale_write",
                    f"The review changed after it was opened: {current.path}",
                    "Reload the review, preserve the newer edits, and retry.",
                    {"path": current.path, "actual_hash": current.content_hash},
                )
            metadata = current.metadata
            replacements: dict[str, Any] = {"updated_at": now.isoformat()}
            for key in (
                "status",
                "current_phase",
                "phases",
                "item_decisions",
                "answers",
                "proposal_refs",
                "previous_review_id",
                "next_review_id",
                "migrated_from",
                "snapshot_id",
                "snapshot_hash",
                "snapshot_history",
                "lifecycle_events",
            ):
                value = getattr(update, key)
                if value is not None:
                    replacements[key] = value
            metadata = replace(metadata, **replacements)
            # Validate the complete metadata before touching the file.
            frontmatter = _metadata_frontmatter(metadata)
            validate_review_metadata(frontmatter, path=current.path)
            body = (
                replace_managed_blocks(current.body, update.managed_blocks)
                if update.managed_blocks
                else current.body
            )
            document = _frontmatter_document(frontmatter, body)
            _atomic_write(
                self.vault_root,
                current.path,
                document,
                expected_hash=expected_hash,
                create=False,
            )
            return self.load_path(current.path)

        return self._idempotent(idempotency_key, "review.update", payload, apply)


def review_artifact_path(review_id: str) -> str:
    return _review_path_from_id(review_id)
