"""Versioned contracts for the goal-to-plan copilot.

The contracts intentionally preserve unknown values. They parse canonical Markdown
without making planning decisions and provide a provider-neutral serialization
boundary for the bridge and Obsidian plugin.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, cast

from lifeos.markdown.parser import ParsedNote, parse_markdown_note
from lifeos.vault import VaultAccessError, iter_vault_markdown, read_vault_markdown

CURRENT_COPILOT_SCHEMA_VERSION = 1
_SUPPORTED_NOTE_SCHEMA_VERSIONS = frozenset({0, 1})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")

GoalHorizon = Literal["open", "weeks", "months", "quarter", "year", "multi-year"]
GoalReadiness = Literal["unknown", "clarifying", "ready", "parked", "not-applicable"]
MilestoneWave = Literal["current", "next", "later"]
SessionStatus = Literal[
    "draft",
    "clarifying",
    "ready",
    "option-review",
    "proposal-created",
    "parked",
    "abandoned",
    "closed",
]
ResponseKind = Literal["answered", "skipped", "unknown", "not-relevant"]
DecisionKind = Literal[
    "ready-to-plan",
    "experiment",
    "park",
    "continue-reflecting",
    "link-existing-plan",
    "abandon",
]
SourceKind = Literal[
    "user-answer",
    "canonical-note",
    "deterministic-fact",
    "adaptive-evidence",
    "agent-assumption",
]


class CopilotContractError(ValueError):
    """Raised when canonical or session data violates a copilot contract."""


@dataclass(frozen=True, slots=True)
class ContractDiagnostic:
    code: str
    severity: Literal["error", "warning"]
    path: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_id: str
    path: str
    content_hash: str
    source_kind: SourceKind = "canonical-note"

    def __post_init__(self) -> None:
        _validate_id(self.source_id, "source_id")
        if not self.path or self.path.startswith("/") or ".." in Path(self.path).parts:
            raise CopilotContractError("path must be a safe vault-relative path")
        if not self.content_hash.startswith("sha256:"):
            raise CopilotContractError("content_hash must use sha256:<hex>")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Milestone:
    milestone_id: str
    title: str
    outcome: str
    status: str = "planned"
    wave: MilestoneWave = "later"
    target_date: date | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.milestone_id, "milestone_id")
        _validate_text(self.title, "milestone title")
        _validate_text(self.outcome, "milestone outcome")
        if self.wave not in {"current", "next", "later"}:
            raise CopilotContractError("milestone wave must be current, next, or later")
        _validate_id_list(self.depends_on, "milestone depends_on")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target_date"] = self.target_date.isoformat() if self.target_date else None
        return data


@dataclass(frozen=True, slots=True)
class NearTermAction:
    task_id: str
    title: str
    status: str = "todo"
    duration: int | None = None
    energy: Literal["low", "medium", "high"] | None = None
    motivation: Literal["low", "medium", "high"] | None = None
    mode: str | None = None
    due: date | None = None
    blocked_by: tuple[str, ...] = ()
    milestone_id: str | None = None
    rationale: str | None = None
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.task_id, "task_id")
        _validate_text(self.title, "task title")
        if self.duration is not None and (
            type(self.duration) is not int or not 1 <= self.duration <= 1440
        ):
            raise CopilotContractError("duration must be an integer from 1 to 1440")
        for name, value in (("energy", self.energy), ("motivation", self.motivation)):
            if value is not None and value not in {"low", "medium", "high"}:
                raise CopilotContractError(f"{name} must be low, medium, high, or unknown")
        if self.mode is not None:
            _validate_text(self.mode, "mode")
        if self.milestone_id is not None:
            _validate_id(self.milestone_id, "milestone_id")
        _validate_id_list(self.blocked_by, "task blocked_by")
        _validate_text_list(self.source_refs, "task source_refs")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["due"] = self.due.isoformat() if self.due else None
        return data


@dataclass(frozen=True, slots=True)
class GoalRecord:
    schema_version: int
    goal_id: str
    title: str
    status: str
    path: str
    content_hash: str
    description: str | None = None
    horizon: GoalHorizon | None = None
    why: str | None = None
    desired_change: str | None = None
    constraints: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    review_cadence: str | None = None
    readiness: GoalReadiness | None = None
    active_plan_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_schema(self.schema_version)
        _validate_id(self.goal_id, "goal_id")
        _validate_text(self.title, "goal title")
        _validate_text(self.status, "goal status")
        if self.horizon is not None and self.horizon not in {
            "open",
            "weeks",
            "months",
            "quarter",
            "year",
            "multi-year",
        }:
            raise CopilotContractError("unsupported goal horizon")
        if self.readiness is not None and self.readiness not in {
            "unknown",
            "clarifying",
            "ready",
            "parked",
            "not-applicable",
        }:
            raise CopilotContractError("unsupported goal readiness")
        _validate_text_list(self.constraints, "constraints")
        _validate_text_list(self.non_goals, "non_goals")
        _validate_text_list(self.active_plan_refs, "active_plan_refs")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanRecord:
    schema_version: int
    plan_id: str
    title: str
    status: str
    path: str
    content_hash: str
    goal_ref: str | None = None
    desired_outcome: str | None = None
    success_evidence: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    review_date: date | None = None
    milestones: tuple[Milestone, ...] = ()
    tasks: tuple[NearTermAction, ...] = ()
    rolling_wave_depth: int | None = None
    supersedes: str | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        _validate_schema(self.schema_version)
        _validate_id(self.plan_id, "plan_id")
        _validate_text(self.title, "plan title")
        _validate_text(self.status, "plan status")
        if self.goal_ref is not None:
            _validate_text(self.goal_ref, "goal_ref")
        for name, values in (
            ("success_evidence", self.success_evidence),
            ("boundaries", self.boundaries),
            ("assumptions", self.assumptions),
        ):
            _validate_text_list(values, name)
        if self.rolling_wave_depth is not None and (
            type(self.rolling_wave_depth) is not int or not 1 <= self.rolling_wave_depth <= 4
        ):
            raise CopilotContractError("rolling_wave_depth must be from 1 to 4")
        _ensure_unique((item.milestone_id for item in self.milestones), "milestone IDs")
        _ensure_unique((item.task_id for item in self.tasks), "task IDs")
        milestone_ids = {item.milestone_id for item in self.milestones}
        for action in self.tasks:
            if action.milestone_id is not None and action.milestone_id not in milestone_ids:
                raise CopilotContractError(
                    f"task {action.task_id} references unknown milestone {action.milestone_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "review_date": self.review_date.isoformat() if self.review_date else None,
            "milestones": [item.to_dict() for item in self.milestones],
            "tasks": [item.to_dict() for item in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class PlanningAnswer:
    question_id: str
    response_kind: ResponseKind
    value: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.question_id, "question_id")
        if self.response_kind == "answered":
            if self.value is None:
                raise CopilotContractError("answered questions require a visible value")
            _validate_text(self.value, "answer value")
        elif self.value is not None:
            raise CopilotContractError("non-answer response kinds cannot carry a value")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    decision_id: str
    kind: DecisionKind
    label: str
    rationale: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.decision_id, "decision_id")
        _validate_text(self.label, "decision label")
        if self.rationale is not None:
            _validate_text(self.rationale, "decision rationale")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanningSession:
    schema_version: int
    session_id: str
    goal_ref: str
    goal_hash: str
    status: SessionStatus
    answers: tuple[PlanningAnswer, ...] = ()
    selected_context_refs: tuple[str, ...] = ()
    excluded_context_refs: tuple[str, ...] = ()
    decisions: tuple[PlanningDecision, ...] = ()
    selected_option_id: str | None = None
    proposal_ids: tuple[str, ...] = ()
    source_revision: int = 1

    def __post_init__(self) -> None:
        _validate_schema(self.schema_version)
        _validate_id(self.session_id, "session_id")
        _validate_text(self.goal_ref, "goal_ref")
        if not self.goal_hash.startswith("sha256:"):
            raise CopilotContractError("goal_hash must use sha256:<hex>")
        if self.status not in {
            "draft",
            "clarifying",
            "ready",
            "option-review",
            "proposal-created",
            "parked",
            "abandoned",
            "closed",
        }:
            raise CopilotContractError("unsupported planning session status")
        _ensure_unique((item.question_id for item in self.answers), "question IDs")
        _ensure_unique((item.decision_id for item in self.decisions), "decision IDs")
        _validate_text_list(self.selected_context_refs, "selected_context_refs")
        _validate_text_list(self.excluded_context_refs, "excluded_context_refs")
        _validate_proposal_ids(self.proposal_ids)
        if set(self.selected_context_refs) & set(self.excluded_context_refs):
            raise CopilotContractError("a context reference cannot be included and excluded")
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise CopilotContractError("source_revision must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "answers": [item.to_dict() for item in self.answers],
            "selected_context_refs": list(self.selected_context_refs),
            "excluded_context_refs": list(self.excluded_context_refs),
            "decisions": [item.to_dict() for item in self.decisions],
            "proposal_ids": list(self.proposal_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PlanningSession:
        _require_keys(data, {"schema_version", "session_id", "goal_ref", "goal_hash", "status"})
        answers_raw = _mapping_list(data.get("answers", []), "answers")
        decisions_raw = _mapping_list(data.get("decisions", []), "decisions")
        return cls(
            schema_version=_integer(data["schema_version"], "schema_version"),
            session_id=_string(data["session_id"], "session_id"),
            goal_ref=_string(data["goal_ref"], "goal_ref"),
            goal_hash=_string(data["goal_hash"], "goal_hash"),
            status=cast(SessionStatus, _string(data["status"], "status")),
            answers=tuple(
                PlanningAnswer(
                    question_id=_string(item.get("question_id"), "question_id"),
                    response_kind=cast(
                        ResponseKind, _string(item.get("response_kind"), "response_kind")
                    ),
                    value=_optional_string(item.get("value"), "value"),
                )
                for item in answers_raw
            ),
            selected_context_refs=_string_tuple(
                data.get("selected_context_refs", []), "selected_context_refs"
            ),
            excluded_context_refs=_string_tuple(
                data.get("excluded_context_refs", []), "excluded_context_refs"
            ),
            decisions=tuple(
                PlanningDecision(
                    decision_id=_string(item.get("decision_id"), "decision_id"),
                    kind=cast(DecisionKind, _string(item.get("kind"), "kind")),
                    label=_string(item.get("label"), "label"),
                    rationale=_optional_string(item.get("rationale"), "rationale"),
                )
                for item in decisions_raw
            ),
            selected_option_id=_optional_string(
                data.get("selected_option_id"), "selected_option_id"
            ),
            proposal_ids=_string_tuple(data.get("proposal_ids", []), "proposal_ids"),
            source_revision=_integer(data.get("source_revision", 1), "source_revision"),
        )


@dataclass(frozen=True, slots=True)
class PlanAssumption:
    assumption_id: str
    statement: str
    source_kind: SourceKind
    source_ref: str | None = None
    confidence: Literal["low", "medium", "high"] = "low"

    def __post_init__(self) -> None:
        _validate_id(self.assumption_id, "assumption_id")
        _validate_text(self.statement, "assumption statement")
        if self.confidence not in {"low", "medium", "high"}:
            raise CopilotContractError("assumption confidence must be low, medium, or high")
        if self.source_ref is not None:
            _validate_text(self.source_ref, "source_ref")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanOption:
    schema_version: int
    option_id: str
    title: str
    strategy: str
    desired_outcome: str
    boundaries: tuple[str, ...]
    assumptions: tuple[PlanAssumption, ...]
    success_evidence: tuple[str, ...]
    risks: tuple[str, ...]
    review_date: date | None
    milestones: tuple[Milestone, ...]
    tradeoffs: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    source_refs: tuple[str, ...]
    reasons_not_fit: tuple[str, ...] = ()
    confidence_label: Literal["low", "medium", "high"] = "low"
    rejected_alternatives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_schema(self.schema_version)
        _validate_id(self.option_id, "option_id")
        _validate_text(self.title, "option title")
        _validate_text(self.strategy, "option strategy")
        _validate_text(self.desired_outcome, "desired_outcome")
        for name, values in (
            ("boundaries", self.boundaries),
            ("success_evidence", self.success_evidence),
            ("risks", self.risks),
            ("tradeoffs", self.tradeoffs),
            ("unresolved_questions", self.unresolved_questions),
            ("source_refs", self.source_refs),
            ("reasons_not_fit", self.reasons_not_fit),
            ("rejected_alternatives", self.rejected_alternatives),
        ):
            _validate_text_list(values, name)
        _ensure_unique((item.assumption_id for item in self.assumptions), "assumption IDs")
        _ensure_unique((item.milestone_id for item in self.milestones), "milestone IDs")
        if self.confidence_label not in {"low", "medium", "high"}:
            raise CopilotContractError("confidence_label must be low, medium, or high")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "review_date": self.review_date.isoformat() if self.review_date else None,
            "assumptions": [item.to_dict() for item in self.assumptions],
            "milestones": [item.to_dict() for item in self.milestones],
        }


@dataclass(frozen=True, slots=True)
class CopilotIndex:
    goals: tuple[GoalRecord, ...]
    plans: tuple[PlanRecord, ...]
    diagnostics: tuple[ContractDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": [item.to_dict() for item in self.goals],
            "plans": [item.to_dict() for item in self.plans],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def content_hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def parse_goal_note(*, path: str, content: str) -> GoalRecord:
    parsed = parse_markdown_note(Path(path), content=content)
    _raise_parser_errors(parsed)
    fm = dict(parsed.frontmatter)
    if fm.get("type") != "goal":
        raise CopilotContractError(f"{path}: type must be goal")
    version = _note_schema_version(fm)
    return GoalRecord(
        schema_version=version,
        goal_id=_required_frontmatter_string(fm, "id", path),
        title=_required_frontmatter_string(fm, "title", path),
        status=_required_frontmatter_string(fm, "status", path),
        path=path,
        content_hash=content_hash(content),
        description=_optional_frontmatter_string(fm, "description", path),
        horizon=cast(GoalHorizon | None, _optional_frontmatter_string(fm, "horizon", path)),
        why=_optional_frontmatter_string(fm, "why", path),
        desired_change=_optional_frontmatter_string(fm, "desired_change", path),
        constraints=_frontmatter_string_tuple(fm, "constraints", path),
        non_goals=_frontmatter_string_tuple(fm, "non_goals", path),
        review_cadence=_optional_frontmatter_string(fm, "review_cadence", path),
        readiness=cast(GoalReadiness | None, _optional_frontmatter_string(fm, "readiness", path)),
        active_plan_refs=_frontmatter_string_tuple(fm, "active_plans", path),
    )


def parse_plan_note(*, path: str, content: str) -> PlanRecord:
    parsed = parse_markdown_note(Path(path), content=content)
    _raise_parser_errors(parsed)
    fm = dict(parsed.frontmatter)
    if fm.get("type") != "plan":
        raise CopilotContractError(f"{path}: type must be plan")
    version = _note_schema_version(fm)
    milestones = tuple(
        _parse_milestone(item, path) for item in _frontmatter_mapping_list(fm, "milestones", path)
    )
    tasks = tuple(
        _parse_action(item, path) for item in _frontmatter_mapping_list(fm, "tasks", path)
    )
    return PlanRecord(
        schema_version=version,
        plan_id=_required_frontmatter_string(fm, "id", path),
        title=_required_frontmatter_string(fm, "title", path),
        status=_required_frontmatter_string(fm, "status", path),
        path=path,
        content_hash=content_hash(content),
        goal_ref=_optional_frontmatter_string(fm, "goal", path),
        desired_outcome=_optional_frontmatter_string(fm, "desired_outcome", path),
        success_evidence=_frontmatter_string_tuple(fm, "success_evidence", path),
        boundaries=_frontmatter_string_tuple(fm, "boundaries", path),
        assumptions=_frontmatter_string_tuple(fm, "assumptions", path),
        review_date=_optional_date(fm.get("review_date"), "review_date", path),
        milestones=milestones,
        tasks=tasks,
        rolling_wave_depth=_optional_integer(
            fm.get("rolling_wave_depth"), "rolling_wave_depth", path
        ),
        supersedes=_optional_frontmatter_string(fm, "supersedes", path),
        superseded_by=_optional_frontmatter_string(fm, "superseded_by", path),
    )


def inspect_copilot_note(vault_root: Path, vault_path: str) -> dict[str, Any]:
    try:
        source = read_vault_markdown(vault_root, vault_path)
    except VaultAccessError as exc:
        raise CopilotContractError(str(exc)) from exc
    parsed = parse_markdown_note(source.path, content=source.content)
    note_type = parsed.frontmatter.get("type")
    if note_type == "goal":
        return {
            "kind": "goal",
            "record": parse_goal_note(path=vault_path, content=source.content).to_dict(),
        }
    if note_type == "plan":
        return {
            "kind": "plan",
            "record": parse_plan_note(path=vault_path, content=source.content).to_dict(),
        }
    raise CopilotContractError("copilot note must have type goal or plan")


def build_copilot_index(vault_root: Path) -> CopilotIndex:
    goals: list[GoalRecord] = []
    plans: list[PlanRecord] = []
    diagnostics: list[ContractDiagnostic] = []
    for root, note_type in (("goals", "goal"), ("plans", "plan")):
        try:
            sources = iter_vault_markdown(vault_root, roots=(root,))
        except VaultAccessError as exc:
            diagnostics.append(
                ContractDiagnostic("scope-unavailable", "error", root, "path", str(exc))
            )
            continue
        for source in sources:
            relative = source.path.relative_to(vault_root).as_posix()
            parsed = parse_markdown_note(source.path, content=source.content)
            if parsed.frontmatter.get("type") != note_type:
                continue
            try:
                record = (
                    parse_goal_note(path=relative, content=source.content)
                    if note_type == "goal"
                    else parse_plan_note(path=relative, content=source.content)
                )
            except CopilotContractError as exc:
                diagnostics.append(
                    ContractDiagnostic(
                        "contract-invalid", "error", relative, "frontmatter", str(exc)
                    )
                )
                continue
            if isinstance(record, GoalRecord):
                goals.append(record)
            else:
                plans.append(record)

    diagnostics.extend(_duplicate_diagnostics(goals, plans))
    goal_ids = {goal.goal_id for goal in goals}
    plan_ids = {plan.plan_id for plan in plans}
    for goal in goals:
        for ref in goal.active_plan_refs:
            normalized = _reference_id(ref)
            if normalized not in plan_ids:
                diagnostics.append(
                    ContractDiagnostic(
                        "unknown-plan-reference",
                        "warning",
                        goal.path,
                        "active_plans",
                        f"Goal references unknown plan: {ref}",
                    )
                )
    for plan in plans:
        if plan.goal_ref is not None and _reference_id(plan.goal_ref) not in goal_ids:
            diagnostics.append(
                ContractDiagnostic(
                    "unknown-goal-reference",
                    "warning",
                    plan.path,
                    "goal",
                    f"Plan references unknown goal: {plan.goal_ref}",
                )
            )
    return CopilotIndex(
        goals=tuple(sorted(goals, key=lambda item: (item.goal_id, item.path))),
        plans=tuple(sorted(plans, key=lambda item: (item.plan_id, item.path))),
        diagnostics=tuple(
            sorted(diagnostics, key=lambda item: (item.path, item.field, item.code, item.message))
        ),
    )


def compatibility_diagnostics(
    *, schema_version: object, path: str
) -> tuple[ContractDiagnostic, ...]:
    if type(schema_version) is not int:
        return (
            ContractDiagnostic(
                "schema-version-invalid", "error", path, "schema_version", "must be an integer"
            ),
        )
    if schema_version not in _SUPPORTED_NOTE_SCHEMA_VERSIONS:
        return (
            ContractDiagnostic(
                "schema-version-unsupported",
                "error",
                path,
                "schema_version",
                f"supported versions are {sorted(_SUPPORTED_NOTE_SCHEMA_VERSIONS)}",
            ),
        )
    if schema_version == 0:
        return (
            ContractDiagnostic(
                "schema-version-legacy",
                "warning",
                path,
                "schema_version",
                "legacy note is readable; optional copilot fields remain unknown",
            ),
        )
    return ()


def _parse_milestone(data: Mapping[str, Any], path: str) -> Milestone:
    return Milestone(
        milestone_id=_string(data.get("milestone_id"), f"{path}: milestone_id"),
        title=_string(data.get("title"), f"{path}: milestone title"),
        outcome=_string(data.get("outcome"), f"{path}: milestone outcome"),
        status=_string(data.get("status", "planned"), f"{path}: milestone status"),
        wave=cast(MilestoneWave, _string(data.get("wave", "later"), f"{path}: wave")),
        target_date=_optional_date(data.get("target_date"), "target_date", path),
        depends_on=_string_tuple(data.get("depends_on", []), f"{path}: depends_on"),
    )


def _parse_action(data: Mapping[str, Any], path: str) -> NearTermAction:
    return NearTermAction(
        task_id=_string(data.get("task_id"), f"{path}: task_id"),
        title=_string(data.get("title"), f"{path}: task title"),
        status=_string(data.get("status", "todo"), f"{path}: task status"),
        duration=_optional_integer(data.get("duration"), "duration", path),
        energy=cast(
            Literal["low", "medium", "high"] | None,
            _optional_string(data.get("energy"), f"{path}: energy"),
        ),
        motivation=cast(
            Literal["low", "medium", "high"] | None,
            _optional_string(data.get("motivation"), f"{path}: motivation"),
        ),
        mode=_optional_string(data.get("mode"), f"{path}: mode"),
        due=_optional_date(data.get("due"), "due", path),
        blocked_by=_string_tuple(data.get("blocked_by", []), f"{path}: blocked_by"),
        milestone_id=_optional_string(data.get("milestone_id"), f"{path}: milestone_id"),
        rationale=_optional_string(data.get("rationale"), f"{path}: rationale"),
        source_refs=_string_tuple(data.get("source_refs", []), f"{path}: source_refs"),
    )


def _note_schema_version(frontmatter: Mapping[str, Any]) -> int:
    raw = frontmatter.get("copilot_schema_version", 0)
    if type(raw) is not int:
        raise CopilotContractError("copilot_schema_version must be an integer")
    if raw not in _SUPPORTED_NOTE_SCHEMA_VERSIONS:
        raise CopilotContractError(f"unsupported copilot_schema_version: {raw}")
    return raw


def _duplicate_diagnostics(
    goals: Iterable[GoalRecord], plans: Iterable[PlanRecord]
) -> list[ContractDiagnostic]:
    entries = [(item.goal_id, item.path, "goal") for item in goals] + [
        (item.plan_id, item.path, "plan") for item in plans
    ]
    by_id: dict[str, list[tuple[str, str]]] = {}
    for stable_id, path, kind in entries:
        by_id.setdefault(stable_id, []).append((path, kind))
    diagnostics: list[ContractDiagnostic] = []
    for stable_id, matches in by_id.items():
        if len(matches) < 2:
            continue
        paths = ", ".join(sorted(path for path, _ in matches))
        for path, _ in matches:
            diagnostics.append(
                ContractDiagnostic(
                    "copilot-id-duplicate",
                    "error",
                    path,
                    "id",
                    f"Stable ID {stable_id!r} is also used by: {paths}",
                )
            )
    return diagnostics


def _reference_id(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("[[") and cleaned.endswith("]]"):
        cleaned = cleaned[2:-2].split("|", 1)[0]
    return Path(cleaned).stem


def _validate_schema(value: int) -> None:
    if type(value) is not int or value not in _SUPPORTED_NOTE_SCHEMA_VERSIONS:
        raise CopilotContractError("unsupported schema_version")


def _validate_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise CopilotContractError(
            f"{name} must use 2-128 lowercase letters, digits, dots, underscores, or hyphens"
        )


def _validate_id_list(values: Iterable[str], name: str) -> None:
    for value in values:
        _validate_id(value, name)
    _ensure_unique(values, name)


def _validate_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CopilotContractError(f"{name} must be a non-empty trimmed string")


def _validate_proposal_ids(values: Iterable[str]) -> None:
    materialized = tuple(values)
    for value in materialized:
        if not isinstance(value, str) or not re.fullmatch(r"prop-\d{8}T\d{6}Z-[a-f0-9]{8}", value):
            raise CopilotContractError("proposal_ids must contain valid durable proposal IDs")
    _ensure_unique(materialized, "proposal_ids")


def _validate_text_list(values: Iterable[str], name: str) -> None:
    materialized = tuple(values)
    for value in materialized:
        _validate_text(value, name)
    _ensure_unique(materialized, name)


def _ensure_unique(values: Iterable[str], name: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise CopilotContractError(f"{name} must be unique")


def _raise_parser_errors(parsed: ParsedNote) -> None:
    errors = [finding for finding in parsed.findings if finding.severity == "error"]
    if errors:
        raise CopilotContractError(errors[0].message)


def _required_frontmatter_string(data: Mapping[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise CopilotContractError(f"{path}: missing required field {key}")
    return _string(data[key], f"{path}: {key}")


def _optional_frontmatter_string(data: Mapping[str, Any], key: str, path: str) -> str | None:
    return _optional_string(data.get(key), f"{path}: {key}")


def _frontmatter_string_tuple(data: Mapping[str, Any], key: str, path: str) -> tuple[str, ...]:
    return _string_tuple(data.get(key, []), f"{path}: {key}")


def _frontmatter_mapping_list(
    data: Mapping[str, Any], key: str, path: str
) -> tuple[Mapping[str, Any], ...]:
    return tuple(_mapping_list(data.get(key, []), f"{path}: {key}"))


def _mapping_list(value: object, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CopilotContractError(f"{name} must be a list of mappings")
    return cast(list[Mapping[str, Any]], value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise CopilotContractError(f"{name} must be a string")
    _validate_text(value, name)
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None or value == "":
        return None
    return _string(value, name)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CopilotContractError(f"{name} must be a list of strings")
    result = tuple(cast(list[str], value))
    _validate_text_list(result, name)
    return result


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise CopilotContractError(f"{name} must be an integer")
    return value


def _optional_integer(value: object, name: str, path: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise CopilotContractError(f"{path}: {name} must be an integer")
    return value


def _optional_date(value: object, name: str, path: str) -> date | None:
    if value is None or value == "":
        return None
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise CopilotContractError(f"{path}: {name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CopilotContractError(f"{path}: {name} must be an ISO date") from exc


def _require_keys(data: Mapping[str, Any], required: set[str]) -> None:
    missing = sorted(required - set(data))
    if missing:
        raise CopilotContractError(f"missing required fields: {', '.join(missing)}")
