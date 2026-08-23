"""Read-only composition of the Obsidian Today dashboard."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from lifeos.attention import evaluate_attention
from lifeos.daily.errors import DailyInteractionError
from lifeos.daily.service import content_hash
from lifeos.markdown.parser import parse_markdown_note
from lifeos.feedback import (
    FeedbackControlService,
    apply_preferences,
    build_adaptive_menu,
    rebuild_evidence_dataset,
)
from lifeos.planning import PlanningError, load_plan_actions
from lifeos.study import StudyError, build_review_plan, load_flashcards
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

SectionState = Literal["ready", "empty", "stale", "blocked", "corrupt", "unavailable"]


@dataclass(frozen=True, slots=True)
class DashboardSection:
    state: SectionState
    data: Any
    code: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TodayInputs:
    day: date
    available_minutes: int = 120
    study_minutes: int = 20
    energy: str = "medium"
    motivation: str = "medium"
    mode: str | None = None
    adaptive_mode: Literal["off", "shadow", "active"] | None = None


@dataclass(frozen=True, slots=True)
class TodayDashboard:
    day: date
    journal: DashboardSection
    planning: DashboardSection
    study: DashboardSection
    experiments: DashboardSection
    inbox: DashboardSection
    proposals: DashboardSection
    attention: DashboardSection
    diagnostics: DashboardSection
    revision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _frontmatter_rows(vault_root: Path, roots: tuple[str, ...], *, note_type: str | None = None) -> tuple[tuple[str, dict[str, Any]], ...]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for source in iter_vault_markdown(vault_root, roots=roots):
        parsed = parse_markdown_note(source.path, content=source.content)
        if any(item.severity == "error" for item in parsed.findings):
            continue
        fm = dict(parsed.frontmatter)
        if note_type is None or fm.get("type") == note_type:
            rows.append((source.relative_path, fm))
    return tuple(sorted(rows))


def _journal(vault_root: Path, day: date) -> DashboardSection:
    path = f"journal/{day.isoformat()}.md"
    try:
        source = read_vault_markdown(vault_root, path)
    except VaultAccessError as exc:
        if exc.code == "not-found":
            return DashboardSection("empty", {"path": path, "metrics": {}, "activities": [], "missing": True})
        return DashboardSection("unavailable", None, exc.code, str(exc))
    parsed = parse_markdown_note(source.path, content=source.content)
    error = next((item for item in parsed.findings if item.severity == "error"), None)
    if error:
        return DashboardSection("corrupt", {"path": path}, error.code, error.message)
    return DashboardSection("ready", {"path": path, "content_hash": content_hash(source.content), "metrics": parsed.frontmatter.get("metrics"), "activities": parsed.frontmatter.get("activities"), "frontmatter": dict(parsed.frontmatter)})


def build_today_dashboard(*, vault_root: Path, runtime_dir: Path, inputs: TodayInputs) -> TodayDashboard:
    revision_parts: list[str] = [
        inputs.day.isoformat(),
        str(inputs.available_minutes),
        inputs.energy,
        inputs.motivation,
        inputs.mode or "",
        inputs.adaptive_mode or "canonical",
    ]
    journal = _journal(vault_root, inputs.day)

    try:
        actions = load_plan_actions(vault_root)
        controls = FeedbackControlService(
            vault_root=vault_root,
            runtime_dir=runtime_dir,
            actor_id="today-dashboard",
        )
        preferences = controls.load()
        dataset, _ = rebuild_evidence_dataset(
            vault_root,
            runtime_dir,
            as_of=inputs.day,
            excluded_event_ids=preferences.excluded_event_ids,
        )
        observations = apply_preferences(dataset.observations, preferences)
        adaptive = build_adaptive_menu(
            actions=actions,
            observations=observations,
            as_of=inputs.day,
            available_minutes=inputs.available_minutes,
            energy=inputs.energy,
            motivation=inputs.motivation,
            mode_filter=inputs.mode,
            adaptive_mode=inputs.adaptive_mode or preferences.mode,
            disabled_dimensions=preferences.disabled_dimensions,
            dismissed_diagnosis_fingerprints=preferences.dismissed_fingerprints(),
        )
        returned_items = adaptive.returned.get("items", ())
        planning_data = dict(adaptive.returned)
        planning_data["adaptive_feedback"] = adaptive.to_dict()
        planning = DashboardSection("ready" if returned_items else "empty", planning_data)
        revision_parts.extend(f"{item.source_path}:{item.task_id}:{item.status}" for item in actions)
    except (PlanningError, DailyInteractionError) as exc:
        code = exc.code if isinstance(exc, DailyInteractionError) else "planning-invalid"
        planning = DashboardSection("corrupt", None, code, str(exc))

    try:
        cards = load_flashcards(vault_root)
        review = build_review_plan(cards=cards, as_of=inputs.day, available_minutes=inputs.study_minutes)
        study = DashboardSection("ready" if review.selected_card_count else "empty", asdict(review))
        revision_parts.extend(f"{card.path}:{card.card_id}:{card.due}" for card in cards)
    except StudyError as exc:
        study = DashboardSection("corrupt", None, "study-invalid", str(exc))

    try:
        experiments_rows = _frontmatter_rows(vault_root, ("experiments",))
        active = tuple({"path": path, "title": fm.get("title") or Path(path).stem} for path, fm in experiments_rows if str(fm.get("status", "active")).casefold() == "active")
        experiments = DashboardSection("ready" if active else "empty", active)
        inbox_rows = _frontmatter_rows(vault_root, ("raw",))
        inbox_items = tuple({"path": path, "title": fm.get("title") or Path(path).stem} for path, fm in inbox_rows if str(fm.get("status", "")).casefold() == "inbox")
        inbox = DashboardSection("ready" if inbox_items else "empty", {"count": len(inbox_items), "items": inbox_items})
        proposal_rows = _frontmatter_rows(vault_root, ("proposals",))
        pending = tuple({"path": path, "title": fm.get("title") or Path(path).stem, "status": fm.get("status")} for path, fm in proposal_rows if str(fm.get("status", "")).casefold() in {"draft", "pending", "approved"})
        proposals = DashboardSection("ready" if pending else "empty", {"count": len(pending), "items": pending})
        revision_parts.extend(path for path, _ in (*experiments_rows, *inbox_rows, *proposal_rows))
    except VaultAccessError as exc:
        experiments = DashboardSection("unavailable", None, exc.code, str(exc))
        inbox = DashboardSection("unavailable", None, exc.code, str(exc))
        proposals = DashboardSection("unavailable", None, exc.code, str(exc))

    attention_result = evaluate_attention(vault_root=vault_root, runtime_dir=runtime_dir, as_of=datetime.combine(inputs.day, datetime.now().time()).astimezone())
    attention = DashboardSection("ready" if attention_result.items else "empty", {"count": len(attention_result.items), "items": tuple(asdict(item) for item in attention_result.items), "diagnostics": attention_result.diagnostics})
    diagnostics_items = tuple(
        {"section": name, "state": section.state, "code": section.code, "detail": section.detail}
        for name, section in (("journal", journal), ("planning", planning), ("study", study), ("experiments", experiments), ("inbox", inbox), ("proposals", proposals))
        if section.state in {"blocked", "corrupt", "unavailable"}
    )
    diagnostics = DashboardSection("ready" if diagnostics_items else "empty", {"count": len(diagnostics_items), "items": diagnostics_items})
    revision = content_hash("\n".join(sorted(revision_parts)))
    return TodayDashboard(inputs.day, journal, planning, study, experiments, inbox, proposals, attention, diagnostics, revision)
