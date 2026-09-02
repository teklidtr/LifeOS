"""Conservative migration and deterministic rebuild for review artifacts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import content_hash
from lifeos.markdown.parser import parse_markdown_note, splice_managed_block
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.history import list_review_history
from lifeos.reviews.progress import rebuild_progress_cache
from lifeos.vault import VaultAccessError, iter_vault_markdown

MigrationState = Literal["ready", "resumable", "already_migrated", "conflict", "malformed"]
_LEGACY = re.compile(
    r"^reviews/(?P<kind>morning|evening)-(?P<day>\d{4}-\d{2}-\d{2})\.md$|^reviews/weekly-(?P<year>\d{4})-W(?P<week>\d{2})\.md$"
)
_CANONICAL_MANAGED_NAMES = {"facts", "items", "continuity", "completion-summary"}


@dataclass(frozen=True, slots=True)
class LegacyReviewSource:
    path: str
    kind: str
    day: str
    content_hash: str
    reflection: str
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewMigrationCandidate:
    review_id: str
    target_path: str
    review_kind: str
    day: str
    sources: tuple[LegacyReviewSource, ...]
    state: MigrationState
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReviewMigrationPreview:
    candidates: tuple[ReviewMigrationCandidate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"candidates": [item.to_dict() for item in self.candidates]}


@dataclass(frozen=True, slots=True)
class ReviewMigrationResult:
    migrated: tuple[str, ...]
    already_migrated: tuple[str, ...]
    conflicts: tuple[ReviewMigrationCandidate, ...]
    preserved_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "migrated": list(self.migrated),
            "already_migrated": list(self.already_migrated),
            "conflicts": [item.to_dict() for item in self.conflicts],
            "preserved_sources": list(self.preserved_sources),
        }


@dataclass(frozen=True, slots=True)
class ReviewRebuildResult:
    artifacts: int
    progress_entries: int
    history_entries: int
    invalid_paths: tuple[str, ...]
    progress_index: str
    history_index: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _legacy_identity(match: re.Match[str]) -> tuple[str, date, str]:
    if match.group("kind"):
        day = date.fromisoformat(match.group("day"))
        return str(match.group("kind")), day, f"daily-{day.isoformat()}"
    year, week = int(match.group("year")), int(match.group("week"))
    day = date.fromisocalendar(year, week, 1)
    return "weekly", day, f"weekly-{year}-W{week:02d}"


def _reflection(content: str, path: Path) -> tuple[str, tuple[str, ...]]:
    parsed = parse_markdown_note(path, content=content)
    diagnostics = [item.message for item in parsed.findings if item.severity == "error"]
    facts = [block for block in parsed.managed_blocks if block.name == "facts"]
    if len(facts) != 1:
        diagnostics.append(
            f"Review managed block 'facts' must appear exactly once; found {len(facts)}."
        )
    if len(parsed.managed_blocks) != len(facts):
        diagnostics.append("Legacy review contains unsupported managed blocks.")
    if diagnostics:
        return parsed.body.strip(), tuple(diagnostics)
    body = splice_managed_block(parsed.body, facts[0], "").strip()
    # Remove the legacy title and reflection heading, while retaining all human-owned text.
    body = re.sub(r"^# .+?\n+", "", body, count=1).strip()
    body = re.sub(r"^## Reflection\s*\n*", "", body, count=1).strip()
    return body, ()


def _is_pristine(service: ReviewArtifactService, review_id: str) -> bool:
    artifact = service.load_id(review_id)
    metadata = artifact.metadata
    if (
        metadata.migrated_from
        or metadata.answers
        or metadata.item_decisions
        or metadata.proposal_refs
        or metadata.snapshot_id
    ):
        return False
    if any(
        phase.completed_sections or phase.skipped_sections or phase.state != "pending"
        for phase in metadata.phases
    ):
        return False
    # Initial managed content and empty reflection headings are the only safe resumable target.
    parsed = parse_markdown_note(Path(artifact.path), content=f"---\n---\n{artifact.body}")
    if any(item.severity == "error" for item in parsed.findings):
        return False
    if (
        len(parsed.managed_blocks) != len(_CANONICAL_MANAGED_NAMES)
        or {block.name for block in parsed.managed_blocks} != _CANONICAL_MANAGED_NAMES
    ):
        return False
    human = parsed.body
    for block in sorted(parsed.managed_blocks, key=lambda item: item.start_offset, reverse=True):
        human = splice_managed_block(human, block, "")
    meaningful = [
        line.strip() for line in human.splitlines() if line.strip() and not line.startswith("#")
    ]
    return meaningful == []


def preview_review_migration(
    *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user"
) -> ReviewMigrationPreview:
    service = ReviewArtifactService(
        vault_root=vault_root, runtime_dir=runtime_dir, actor_id=actor_id
    )
    grouped: dict[str, list[LegacyReviewSource]] = {}
    identities: dict[str, tuple[str, date]] = {}
    try:
        sources = iter_vault_markdown(vault_root, roots=("reviews",))
    except VaultAccessError as exc:
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check vault access and retry."
        ) from exc
    for source in sources:
        match = _LEGACY.fullmatch(source.relative_path)
        if match is None:
            continue
        kind, day, review_id = _legacy_identity(match)
        reflection, diagnostics = _reflection(source.content, source.path)
        grouped.setdefault(review_id, []).append(
            LegacyReviewSource(
                source.relative_path,
                kind,
                day.isoformat(),
                content_hash(source.content),
                reflection,
                diagnostics,
            )
        )
        identities[review_id] = ("weekly" if kind == "weekly" else "daily", day)
    candidates: list[ReviewMigrationCandidate] = []
    for review_id, legacy in sorted(grouped.items()):
        review_kind, day = identities[review_id]
        target_path = f"reviews/{review_kind}/{review_id.removeprefix(review_kind + '-')}.md"
        diagnostics = tuple(item for source in legacy for item in source.diagnostics)
        state: MigrationState = "malformed" if diagnostics else "ready"
        target = vault_root / target_path
        if target.exists():
            try:
                artifact = service.load_path(target_path)
                legacy_paths = {item.path for item in legacy}
                if legacy_paths <= set(artifact.metadata.migrated_from):
                    state = "already_migrated"
                elif _is_pristine(service, review_id):
                    state = "resumable"
                else:
                    state = "conflict"
                    diagnostics = (
                        *diagnostics,
                        "Canonical target already exists with non-migration content.",
                    )
            except DailyInteractionError as exc:
                state = "conflict"
                diagnostics = (*diagnostics, str(exc))
        candidates.append(
            ReviewMigrationCandidate(
                review_id,
                target_path,
                review_kind,
                day.isoformat(),
                tuple(sorted(legacy, key=lambda item: item.path)),
                state,
                diagnostics,
            )
        )
    return ReviewMigrationPreview(tuple(candidates))


def _insert_import(body: str, heading: str, label: str, reflection: str) -> str:
    if not reflection.strip():
        return body
    marker = f"### Imported {label} reflection"
    if marker in body:
        return body
    match = re.search(rf"(?m)^{re.escape(heading)}\s*$", body)
    if match is None:
        raise DailyInteractionError(
            "invalid_review_artifact",
            f"Missing section {heading}.",
            "Repair the canonical review template.",
        )
    next_heading = re.search(r"(?m)^##\s+", body[match.end() :])
    end = match.end() + (next_heading.start() if next_heading else len(body[match.end() :]))
    insertion = f"\n\n{marker}\n\n{reflection.strip()}\n"
    return body[:end] + insertion + "\n" + body[end:]


def apply_review_migration(
    *,
    vault_root: Path,
    runtime_dir: Path,
    actor_id: str,
    now: datetime,
    idempotency_key: str,
    expected_source_hashes: dict[str, str] | None = None,
) -> ReviewMigrationResult:
    if now.tzinfo is None:
        raise DailyInteractionError(
            "invalid_datetime",
            "Migration timestamp must include a timezone.",
            "Use an aware datetime.",
        )
    service = ReviewArtifactService(
        vault_root=vault_root, runtime_dir=runtime_dir, actor_id=actor_id
    )
    preview = preview_review_migration(
        vault_root=vault_root, runtime_dir=runtime_dir, actor_id=actor_id
    )
    migrated: list[str] = []
    already: list[str] = []
    conflicts: list[ReviewMigrationCandidate] = []
    preserved: list[str] = []
    for candidate in preview.candidates:
        preserved.extend(item.path for item in candidate.sources)
        if expected_source_hashes is not None:
            changed = [
                source.path
                for source in candidate.sources
                if expected_source_hashes.get(source.path) != source.content_hash
            ]
            if changed:
                conflicts.append(
                    replace(
                        candidate,
                        state="conflict",
                        diagnostics=(
                            *candidate.diagnostics,
                            f"Legacy source changed after preview: {', '.join(changed)}",
                        ),
                    )
                )
                continue
        if candidate.state == "already_migrated":
            already.append(candidate.review_id)
            continue
        if candidate.state not in {"ready", "resumable"}:
            conflicts.append(candidate)
            continue
        artifact = service.open_or_create(
            kind=candidate.review_kind,
            day=date.fromisoformat(candidate.day),
            timezone="local",
            now=now,
            idempotency_key=f"{idempotency_key}-{candidate.review_id.lower()}-open",
        )
        body = artifact.body
        if candidate.review_kind == "daily":
            for source in candidate.sources:
                heading = (
                    "## Morning reflection" if source.kind == "morning" else "## Evening reflection"
                )
                body = _insert_import(body, heading, source.kind, source.reflection)
        else:
            body = _insert_import(
                body, "## Weekly reflection", "weekly", candidate.sources[0].reflection
            )
        artifact = service.update(
            review_id=artifact.metadata.review_id,
            expected_hash=artifact.content_hash,
            idempotency_key=f"{idempotency_key}-{candidate.review_id.lower()}-apply",
            now=now,
            update=ReviewArtifactUpdate(
                migrated_from=tuple(item.path for item in candidate.sources),
                human_body=body,
            ),
        )
        migrated.append(artifact.metadata.review_id)
    return ReviewMigrationResult(
        tuple(migrated), tuple(already), tuple(conflicts), tuple(sorted(set(preserved)))
    )


def rebuild_review_state(
    *, vault_root: Path, runtime_dir: Path, actor_id: str = "local-user"
) -> ReviewRebuildResult:
    service = ReviewArtifactService(
        vault_root=vault_root, runtime_dir=runtime_dir, actor_id=actor_id
    )
    invalid: list[str] = []
    try:
        sources = tuple(
            item
            for item in iter_vault_markdown(vault_root, roots=("reviews",))
            if item.relative_path.startswith(("reviews/daily/", "reviews/weekly/"))
        )
    except VaultAccessError as exc:
        raise DailyInteractionError(
            "storage_unavailable", str(exc), "Check vault access and retry."
        ) from exc
    for source in sources:
        try:
            service.load_path(source.relative_path)
        except DailyInteractionError:
            invalid.append(source.relative_path)
    progress = rebuild_progress_cache(vault_root=vault_root, runtime_dir=runtime_dir)
    history = [item.to_dict() for item in list_review_history(service=service)]
    target = runtime_dir / "reviews" / "history-index.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(history, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return ReviewRebuildResult(
        len(sources),
        len(progress),
        len(history),
        tuple(sorted(invalid)),
        str(runtime_dir / "reviews" / "progress-index.json"),
        str(target),
    )
