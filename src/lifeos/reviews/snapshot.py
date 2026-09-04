"""Deterministic, provenance-rich snapshots for canonical review artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from lifeos.daily import content_hash, load_execution_records
from lifeos.experiments.reviews import daily_experiment_section, weekly_experiment_section
from lifeos.reviews.artifact import ReviewArtifactService, ReviewArtifactUpdate
from lifeos.reviews.contracts import (
    ReviewArtifact,
    ReviewItemSnapshot,
    ReviewSectionSnapshot,
    ReviewSnapshot,
    ReviewSnapshotRecord,
    ReviewSourceReference,
    stable_fingerprint,
)
from lifeos.markdown.parser import parse_markdown_note
from lifeos.patterns.reviews import daily_pattern_review_section, weekly_pattern_review_section
from lifeos.reviews.workflow import ReviewItem, ReviewSection, build_review_workflow
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown


def _source_reference(
    vault_root: Path, item: ReviewItem, generated_at: str
) -> tuple[ReviewSourceReference, ...]:
    if not item.source_path:
        return ()
    path = item.source_path
    # A review can surface its own pending phase through attention. Hashing the
    # artifact here would make every managed refresh change the next snapshot.
    if path.startswith(("reviews/daily/", "reviews/weekly/")):
        return (ReviewSourceReference(path=path, detail=item.detail, observed_at=generated_at),)
    if ":" in path.split("/", 1)[0] or path.startswith("execution:"):
        return (ReviewSourceReference(path=path, detail=item.detail, observed_at=generated_at),)
    try:
        source = read_vault_markdown(vault_root, path)
    except VaultAccessError:
        return (
            ReviewSourceReference(
                path=path,
                detail="Source was unavailable during snapshot.",
                observed_at=generated_at,
            ),
        )
    return (
        ReviewSourceReference(
            path=path,
            content_hash="sha256:" + content_hash(source.content),
            detail=item.detail,
            observed_at=generated_at,
        ),
    )


def _snapshot_item(
    vault_root: Path, section: ReviewSection, item: ReviewItem, generated_at: str
) -> ReviewItemSnapshot:
    sources = _source_reference(vault_root, item, generated_at)
    fingerprint = stable_fingerprint(
        section.section_id,
        item.item_id,
        item.title,
        item.detail,
        item.action or "",
        *(f"{source.path}:{source.content_hash or 'unknown'}" for source in sources),
    )
    return ReviewItemSnapshot(
        item_id=item.item_id,
        section_id=section.section_id,
        title=item.title,
        detail=item.detail,
        evidence_fingerprint=fingerprint,
        state=section.state,
        action=item.action,
        sources=sources,
        diagnostic=section.diagnostic if section.state == "unavailable" else None,
    )


def _snapshot_section(
    vault_root: Path, section: ReviewSection, generated_at: str
) -> ReviewSectionSnapshot:
    return ReviewSectionSnapshot(
        section_id=section.section_id,
        title=section.title,
        optional=section.optional,
        state=section.state,
        items=tuple(
            _snapshot_item(vault_root, section, item, generated_at) for item in section.items
        ),
        diagnostic=section.diagnostic,
    )


def _daily_evidence_section(
    vault_root: Path, day: date, generated_at: str
) -> ReviewSectionSnapshot:
    items: list[ReviewItemSnapshot] = []
    journal_path = f"journal/{day.isoformat()}.md"
    try:
        source = read_vault_markdown(vault_root, journal_path)
        parsed = parse_markdown_note(source.path, content=source.content)
        body = parsed.body.casefold()
        journal_hash = "sha256:" + content_hash(source.content)
        morning = "## morning check-in" in body or bool(parsed.frontmatter.get("metrics"))
        evening = "## evening check-in" in body
        for phase, present in (("morning", morning), ("evening", evening)):
            detail = (
                f"{phase.title()} check-in is recorded."
                if present
                else f"No {phase} check-in is recorded; this remains unknown, not a failure."
            )
            items.append(
                ReviewItemSnapshot(
                    item_id=f"daily-evidence:{phase}-checkin",
                    section_id="daily-evidence",
                    title=f"{phase.title()} check-in",
                    detail=detail,
                    evidence_fingerprint=stable_fingerprint(
                        journal_path, journal_hash, phase, present
                    ),
                    state="ready",
                    action="open",
                    sources=(
                        ReviewSourceReference(journal_path, journal_hash, detail, generated_at),
                    ),
                )
            )
    except VaultAccessError:
        for phase in ("morning", "evening"):
            items.append(
                ReviewItemSnapshot(
                    item_id=f"daily-evidence:{phase}-checkin",
                    section_id="daily-evidence",
                    title=f"{phase.title()} check-in",
                    detail=f"No journal evidence is available for the {phase} check-in; this remains unknown.",
                    evidence_fingerprint=stable_fingerprint(journal_path, phase, "missing"),
                    state="ready",
                    action="checkin",
                    sources=(
                        ReviewSourceReference(
                            journal_path, None, "Journal note is absent.", generated_at
                        ),
                    ),
                )
            )
    try:
        records = tuple(
            record for record in load_execution_records(vault_root) if record.day == day
        )
        detail = f"{len(records)} explicit task outcome{'s' if len(records) != 1 else ''} recorded today."
        refs = tuple(
            ReviewSourceReference(record.plan_path, None, record.outcome, generated_at)
            for record in records
        )
        items.append(
            ReviewItemSnapshot(
                item_id="daily-evidence:task-outcomes",
                section_id="daily-evidence",
                title="Task outcomes",
                detail=detail,
                evidence_fingerprint=stable_fingerprint(
                    *(f"{record.event_id}:{record.outcome}" for record in records), day
                ),
                state="ready",
                action="reconcile",
                sources=refs,
            )
        )
    except Exception as exc:
        items.append(
            ReviewItemSnapshot(
                item_id="daily-evidence:task-outcomes",
                section_id="daily-evidence",
                title="Task outcomes",
                detail="Task outcome evidence is temporarily unavailable.",
                evidence_fingerprint=stable_fingerprint(
                    day, "outcomes-unavailable", type(exc).__name__
                ),
                state="unavailable",
                diagnostic=str(exc),
            )
        )
    return ReviewSectionSnapshot(
        "daily-evidence", "Today's explicit evidence", False, "ready", tuple(items)
    )


def _weekly_evidence_sections(
    vault_root: Path, runtime_dir: Path, range_start: date, range_end: date, generated_at: str
) -> tuple[ReviewSectionSnapshot, ...]:
    sections: list[ReviewSectionSnapshot] = []
    try:
        records = tuple(
            record
            for record in load_execution_records(vault_root)
            if range_start <= record.day <= range_end
        )
        counts: dict[str, int] = {}
        for record in records:
            counts[record.outcome] = counts.get(record.outcome, 0) + 1
        detail = (
            ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
            or "No explicit task outcomes were recorded; missing evidence remains unknown."
        )
        refs = tuple(
            ReviewSourceReference(
                record.plan_path, None, f"{record.day}: {record.outcome}", generated_at
            )
            for record in records
        )
        execution = ReviewItemSnapshot(
            "weekly-evidence:execution",
            "weekly-evidence",
            "Execution evidence",
            detail,
            stable_fingerprint(
                range_start,
                range_end,
                *(f"{record.event_id}:{record.outcome}" for record in records),
            ),
            "ready",
            "review",
            refs,
        )
        sections.append(
            ReviewSectionSnapshot(
                "weekly-evidence", "Week in explicit evidence", False, "ready", (execution,)
            )
        )
    except Exception as exc:
        sections.append(
            ReviewSectionSnapshot(
                "weekly-evidence", "Week in explicit evidence", False, "unavailable", (), str(exc)
            )
        )

    experiments: list[ReviewItemSnapshot] = []
    try:
        for source in iter_vault_markdown(vault_root, roots=("experiments",)):
            parsed = parse_markdown_note(source.path, content=source.content)
            if any(finding.severity == "error" for finding in parsed.findings):
                continue
            if str(parsed.frontmatter.get("status", "")).casefold() != "active":
                continue
            title = str(parsed.frontmatter.get("title") or source.path.stem)
            required = parsed.frontmatter.get("required_metrics", [])
            metric_names = (
                tuple(item for item in required if isinstance(item, str))
                if isinstance(required, list)
                else ()
            )
            source_hash = "sha256:" + content_hash(source.content)
            detail = f"Active experiment; required observations: {', '.join(metric_names) if metric_names else 'none declared'}."
            experiments.append(
                ReviewItemSnapshot(
                    f"experiments:{stable_fingerprint(source.relative_path)[-16:]}",
                    "experiments",
                    title,
                    detail,
                    stable_fingerprint(source.relative_path, source_hash, metric_names),
                    "ready",
                    "open",
                    (
                        ReviewSourceReference(
                            source.relative_path, source_hash, detail, generated_at
                        ),
                    ),
                )
            )
        sections.append(
            ReviewSectionSnapshot(
                "experiments",
                "Active experiments",
                True,
                "ready" if experiments else "empty",
                tuple(experiments),
            )
        )
    except VaultAccessError as exc:
        sections.append(
            ReviewSectionSnapshot(
                "experiments", "Active experiments", True, "unavailable", (), str(exc)
            )
        )

    health_items: list[ReviewItemSnapshot] = []
    registry_path = runtime_dir / "registry.db"
    health_items.append(
        ReviewItemSnapshot(
            "system-health:registry",
            "system-health",
            "Disposable registry",
            "Registry is present and rebuildable."
            if registry_path.exists()
            else "Registry is absent; review artifacts remain canonical and the index can be rebuilt.",
            stable_fingerprint("registry", registry_path.exists()),
            "ready",
            "status",
            (),
        )
    )
    ownership_path = vault_root / "system" / "generated-ownership.json"
    health_items.append(
        ReviewItemSnapshot(
            "system-health:ownership",
            "system-health",
            "Generated ownership manifest",
            "Ownership manifest is present."
            if ownership_path.exists()
            else "Ownership manifest is absent; consequential proposal preflight may fail closed.",
            stable_fingerprint("ownership", ownership_path.exists()),
            "ready",
            "status",
            (),
        )
    )
    sections.append(
        ReviewSectionSnapshot("system-health", "System health", True, "ready", tuple(health_items))
    )
    return tuple(sections)


def build_review_snapshot(
    *,
    vault_root: Path,
    runtime_dir: Path,
    kind: str,
    day: date,
    generated_at: datetime,
    urgent_pattern_ids: tuple[str, ...] = (),
    pinned_pattern_ids: tuple[str, ...] = (),
) -> ReviewSnapshot:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    if kind not in {"daily", "weekly"}:
        raise ValueError("kind must be daily or weekly")
    # The existing evening workflow contains the complete daily evidence set.
    workflow_kind: Literal["evening", "weekly"] = "evening" if kind == "daily" else "weekly"
    workflow = build_review_workflow(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        kind=workflow_kind,
        day=day,
    )
    generated = generated_at.isoformat()
    sections = tuple(
        _snapshot_section(vault_root, section, generated) for section in workflow.sections
    )
    if kind == "daily":
        sections = (
            *sections,
            _daily_evidence_section(vault_root, day, generated),
            daily_experiment_section(
                vault_root=vault_root, runtime_dir=runtime_dir, day=day, generated_at=generated_at
            ),
            daily_pattern_review_section(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
                generated_at=generated_at,
                urgent_pattern_ids=urgent_pattern_ids,
                pinned_pattern_ids=pinned_pattern_ids,
            ),
        )
    else:
        pattern_section = weekly_pattern_review_section(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            generated_at=generated_at,
        )
        sections = (
            *sections,
            *_weekly_evidence_sections(
                vault_root, runtime_dir, workflow.range_start, workflow.range_end, generated
            ),
            weekly_experiment_section(
                vault_root=vault_root,
                runtime_dir=runtime_dir,
                range_start=workflow.range_start,
                range_end=workflow.range_end,
                generated_at=generated_at,
            ),
            pattern_section,
        )
    diagnostics = tuple(
        f"{section.section_id}: {section.diagnostic}"
        for section in sections
        if section.state == "unavailable" and section.diagnostic
    )
    payload: dict[str, Any] = {
        "kind": kind,
        "period_start": workflow.range_start.isoformat(),
        "period_end": workflow.range_end.isoformat(),
        "sections": [asdict(section) for section in sections],
        "diagnostics": diagnostics,
    }
    digest = "sha256:" + content_hash(json.dumps(payload, sort_keys=True, default=str))
    snapshot_id = f"snapshot:{kind}:{workflow.range_start.isoformat()}:{digest[-16:]}"
    return ReviewSnapshot(snapshot_id, generated, digest, sections, diagnostics)


def render_snapshot_facts(snapshot: ReviewSnapshot) -> str:
    lines = [
        "## Review facts",
        "",
        f"Snapshot `{snapshot.snapshot_id}` generated {snapshot.generated_at}.",
        "",
    ]
    for section in snapshot.sections:
        lines.append(f"### {section.title}")
        if section.state == "unavailable":
            lines.append(f"- Unavailable: {section.diagnostic or 'No diagnostic was provided.'}")
        elif not section.items:
            lines.append("- Nothing requiring attention.")
        else:
            for item in section.items:
                source = item.sources[0].path if item.sources else None
                suffix = f" ([source]({source}))" if source else ""
                lines.append(f"- **{item.title}**: {item.detail}{suffix}")
        lines.append("")
    if snapshot.diagnostics:
        lines.extend(
            ["### Snapshot diagnostics", *[f"- {item}" for item in snapshot.diagnostics], ""]
        )
    return "\n".join(lines).rstrip()


def render_snapshot_items(snapshot: ReviewSnapshot) -> str:
    lines = ["## Review items", ""]
    for section in snapshot.sections:
        lines.append(f"### {section.title}")
        if not section.items:
            lines.append("- No items.")
        for item in section.items:
            title = " ".join(item.title.splitlines())
            lines.append(
                f"- [ ] {title} <!-- lifeos:item {item.item_id} {item.evidence_fingerprint} -->"
            )
            if item.action:
                lines.append(f"  - Suggested action: `{item.action}`")
            for source in item.sources:
                hash_text = f" at `{source.content_hash}`" if source.content_hash else ""
                lines.append(f"  - Source: [{source.path}]({source.path}){hash_text}")
        lines.append("")
    return "\n".join(lines).rstrip()


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
    snapshot = build_review_snapshot(
        vault_root=service.vault_root,
        runtime_dir=runtime_dir,
        kind=artifact.metadata.review_kind,
        day=artifact.metadata.period_start,
        generated_at=generated_at,
        urgent_pattern_ids=urgent_pattern_ids,
        pinned_pattern_ids=pinned_pattern_ids,
    )
    from lifeos.reviews.history import (
        adjacent_reviews,
        apply_continuity_to_snapshot,
        build_review_continuity,
        render_review_continuity,
    )

    previous, _ = adjacent_reviews(service=service, artifact=artifact)
    continuity = build_review_continuity(current_snapshot=snapshot, previous=previous)
    snapshot = apply_continuity_to_snapshot(snapshot, continuity)
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
