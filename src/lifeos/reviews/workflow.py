"""Deterministic inputs and resumable state for guided LifeOS reviews."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from lifeos.attention import evaluate_attention
from lifeos.daily import DailyInteractionService, ReviewNoteRequest, content_hash, load_execution_records
from lifeos.daily.errors import DailyInteractionError
from lifeos.feedback import build_feedback_review_summary
from lifeos.markdown.parser import parse_markdown_note
from lifeos.planning import PlanningError, load_plan_actions
from lifeos.study import StudyError, build_review_plan, load_flashcards
from lifeos.vault import VaultAccessError, iter_vault_markdown

ReviewKind = Literal["morning", "evening", "weekly"]
SectionState = Literal["ready", "empty", "unavailable"]


@dataclass(frozen=True, slots=True)
class ReviewItem:
    item_id: str
    title: str
    detail: str
    source_path: str | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewSection:
    section_id: str
    title: str
    optional: bool
    state: SectionState
    items: tuple[ReviewItem, ...]
    diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewProgress:
    review_id: str
    completed_sections: tuple[str, ...] = ()
    skipped_sections: tuple[str, ...] = ()
    current_section: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewWorkflow:
    review_id: str
    kind: ReviewKind
    day: date
    range_start: date
    range_end: date
    sections: tuple[ReviewSection, ...]
    progress: ReviewProgress
    facts_markdown: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _review_identity(kind: ReviewKind, day: date) -> tuple[str, date, date]:
    if kind == "weekly":
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
        return f"weekly-{start.isocalendar().year}-W{start.isocalendar().week:02d}", start, end
    return f"{kind}-{day.isoformat()}", day, day


def _stable_item(section: str, key: str, title: str, detail: str, path: str | None = None, action: str | None = None) -> ReviewItem:
    digest = hashlib.sha256(f"{section}\0{key}".encode()).hexdigest()[:16]
    return ReviewItem(f"{section}:{digest}", title, detail, path, action)


def _scan_frontmatter(vault_root: Path, roots: tuple[str, ...]) -> tuple[tuple[str, dict[str, Any]], ...]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for source in iter_vault_markdown(vault_root, roots=roots):
        parsed = parse_markdown_note(source.path, content=source.content)
        if not any(finding.severity == "error" for finding in parsed.findings):
            rows.append((source.relative_path, dict(parsed.frontmatter)))
    return tuple(sorted(rows))


def _load_progress(runtime_dir: Path, review_id: str) -> ReviewProgress:
    path = runtime_dir / "reviews" / f"{review_id}.json"
    if not path.exists():
        return ReviewProgress(review_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ReviewProgress(
            review_id,
            tuple(sorted(str(item) for item in raw.get("completed_sections", []))),
            tuple(sorted(str(item) for item in raw.get("skipped_sections", []))),
            raw.get("current_section") if isinstance(raw.get("current_section"), str) else None,
        )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise DailyInteractionError(
            "review_progress_corrupt",
            "Saved review progress is corrupt.",
            "Reset disposable review progress and reopen the review.",
        ) from exc


def save_progress(
    runtime_dir: Path,
    *,
    review_id: str,
    completed_sections: tuple[str, ...] = (),
    skipped_sections: tuple[str, ...] = (),
    current_section: str | None = None,
) -> ReviewProgress:
    progress = ReviewProgress(
        review_id,
        tuple(sorted(set(completed_sections))),
        tuple(sorted(set(skipped_sections))),
        current_section,
    )
    path = runtime_dir / "reviews" / f"{review_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(progress), sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return progress


def build_review_workflow(
    *,
    vault_root: Path,
    runtime_dir: Path,
    kind: ReviewKind,
    day: date,
) -> ReviewWorkflow:
    review_id, range_start, range_end = _review_identity(kind, day)
    sections: list[ReviewSection] = []

    try:
        attention = evaluate_attention(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            as_of=__import__("datetime").datetime.combine(day, __import__("datetime").time(22, 0)).astimezone(),
        )
        items = tuple(
            _stable_item("attention", item.item_id, item.title, item.explanation, item.evidence[0].path if item.evidence else None, "reconcile")
            for item in attention.items
        )
        sections.append(ReviewSection("attention", "Unresolved loops", False, "ready" if items else "empty", items))
    except Exception as exc:
        sections.append(ReviewSection("attention", "Unresolved loops", False, "unavailable", (), str(exc)))

    try:
        inbox_rows = _scan_frontmatter(vault_root, ("raw",))
        items = tuple(
            _stable_item("inbox", path, str(fm.get("title") or Path(path).stem), "Unprocessed capture", path, "process")
            for path, fm in inbox_rows
            if str(fm.get("status", "")).casefold() == "inbox"
        )
        sections.append(ReviewSection("inbox", "Inbox", False, "ready" if items else "empty", items))
    except VaultAccessError as exc:
        sections.append(ReviewSection("inbox", "Inbox", False, "unavailable", (), str(exc)))

    try:
        actions = load_plan_actions(vault_root)
        active = tuple(
            _stable_item("plans", action.task_id, action.title, f"{action.plan}; status {action.status}", action.source_path, "open")
            for action in actions
            if action.status in {"todo", "active", "pending"}
        )
        sections.append(ReviewSection("plans", "Active plans and actions", False, "ready" if active else "empty", active))
    except PlanningError as exc:
        sections.append(ReviewSection("plans", "Active plans and actions", False, "unavailable", (), str(exc)))

    if kind == "weekly":
        try:
            feedback_items = tuple(
                _stable_item(
                    "adaptive-feedback",
                    suggestion.suggestion_id,
                    suggestion.title,
                    f"{suggestion.detail} Confidence: {suggestion.confidence}.",
                    suggestion.target_path or None,
                    suggestion.proposed_action,
                )
                for suggestion in build_feedback_review_summary(vault_root=vault_root, as_of=day)
            )
            sections.append(
                ReviewSection(
                    "adaptive-feedback",
                    "Adaptive planning feedback",
                    True,
                    "ready" if feedback_items else "empty",
                    feedback_items,
                )
            )
        except (DailyInteractionError, PlanningError, ValueError) as exc:
            sections.append(
                ReviewSection(
                    "adaptive-feedback",
                    "Adaptive planning feedback",
                    True,
                    "unavailable",
                    (),
                    str(exc),
                )
            )

    try:
        records = [record for record in load_execution_records(vault_root) if range_start <= record.day <= range_end]
        grouped: dict[str, list[Any]] = {}
        for record in records:
            if record.outcome in {"skipped", "deferred", "partial"}:
                grouped.setdefault(record.task_id, []).append(record)
        repeated = tuple(
            _stable_item(
                "avoidance",
                task_id,
                f"Review {task_id}",
                f"{len(events)} incomplete or avoided attempts; inspect scope and blockers without assuming failure.",
                events[-1].plan_path,
                "diagnose",
            )
            for task_id, events in sorted(grouped.items())
            if len(events) >= 2
        )
        sections.append(ReviewSection("avoidance", "Repeated friction", True, "ready" if repeated else "empty", repeated))
    except DailyInteractionError as exc:
        sections.append(ReviewSection("avoidance", "Repeated friction", True, "unavailable", (), str(exc)))

    try:
        plan = build_review_plan(cards=load_flashcards(vault_root), as_of=day, available_minutes=60)
        items = tuple(
            _stable_item("study", session.topic, session.topic, f"{len(session.card_ids)} cards; {session.estimated_minutes} minutes; {session.overdue_cards} overdue", session.card_paths[0] if session.card_paths else None, "study")
            for session in plan.sessions
        )
        sections.append(ReviewSection("study", "Study backlog", True, "ready" if items else "empty", items))
    except StudyError as exc:
        sections.append(ReviewSection("study", "Study backlog", True, "unavailable", (), str(exc)))

    try:
        proposals = _scan_frontmatter(vault_root, ("proposals",))
        items = tuple(
            _stable_item("proposals", path, str(fm.get("title") or Path(path).stem), f"Proposal is {fm.get('status')}", path, "review")
            for path, fm in proposals
            if str(fm.get("status", "")).casefold() in {"draft", "pending", "approved", "stale"}
        )
        sections.append(ReviewSection("proposals", "Proposals", True, "ready" if items else "empty", items))
    except VaultAccessError as exc:
        sections.append(ReviewSection("proposals", "Proposals", True, "unavailable", (), str(exc)))

    facts_lines = [f"## {kind.title()} review facts", ""]
    for section in sections:
        facts_lines.append(f"### {section.title}")
        if section.state == "unavailable":
            facts_lines.append(f"- Unavailable: {section.diagnostic}")
        elif not section.items:
            facts_lines.append("- Nothing requiring attention.")
        else:
            for item in section.items:
                suffix = f" ([source]({item.source_path}))" if item.source_path else ""
                facts_lines.append(f"- **{item.title}**: {item.detail}{suffix}")
        facts_lines.append("")
    return ReviewWorkflow(
        review_id,
        kind,
        day,
        range_start,
        range_end,
        tuple(sections),
        _load_progress(runtime_dir, review_id),
        "\n".join(facts_lines).rstrip(),
    )


def save_review_note(
    *,
    vault_root: Path,
    runtime_dir: Path,
    actor_id: str,
    workflow: ReviewWorkflow,
    idempotency_key: str,
    expected_hash: str | None = None,
) -> dict[str, Any]:
    service = DailyInteractionService(vault_root=vault_root, runtime_dir=runtime_dir, actor_id=actor_id)
    result = service.create_review_note(
        ReviewNoteRequest(
            idempotency_key,
            workflow.kind,
            workflow.day,
            workflow.facts_markdown,
            expected_hash,
        )
    )
    return result.to_dict()
