"""Rolling-wave decomposition of a selected plan option."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Mapping, Protocol

from .contracts import GoalHorizon, Milestone, NearTermAction, PlanOption

ActionKind = Literal["general", "study-session", "exercise", "rest", "hobby", "experiment"]


class DecompositionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DecompositionPolicy:
    review_window_days: int = 14
    max_actions: int = 6
    max_action_minutes: int = 180

    def __post_init__(self) -> None:
        if type(self.review_window_days) is not int or not 1 <= self.review_window_days <= 31:
            raise DecompositionError("review_window_days must be from 1 to 31")
        if type(self.max_actions) is not int or not 1 <= self.max_actions <= 12:
            raise DecompositionError("max_actions must be from 1 to 12")
        if type(self.max_action_minutes) is not int or not 15 <= self.max_action_minutes <= 480:
            raise DecompositionError("max_action_minutes must be from 15 to 480")


@dataclass(frozen=True, slots=True)
class ActionSuggestion:
    title: str
    milestone_id: str
    duration: int | None
    energy: Literal["low", "medium", "high"] | None
    motivation: Literal["low", "medium", "high"] | None
    mode: str | None
    blocked_by: tuple[str, ...] = ()
    due: date | None = None
    rationale: str = ""
    verification: str = ""
    kind: ActionKind = "general"
    source_refs: tuple[str, ...] = ()
    task_id: str | None = None


class RollingWaveAdapter(Protocol):
    def decompose(
        self,
        *,
        option: PlanOption,
        current_milestones: tuple[Milestone, ...],
        max_actions: int,
    ) -> tuple[ActionSuggestion, ...]: ...


@dataclass(frozen=True, slots=True)
class DecompositionFinding:
    code: str
    severity: Literal["error", "warning", "information"]
    item_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GeneratedAction:
    action: NearTermAction
    verification: str
    kind: ActionKind

    def to_dict(self) -> dict[str, object]:
        return {
            **self.action.to_dict(),
            "verification": self.verification,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class DecompositionResult:
    schema_version: int
    option_id: str
    current_window_days: int
    rolling_wave_depth: int
    milestones: tuple[Milestone, ...]
    actions: tuple[GeneratedAction, ...]
    findings: tuple[DecompositionFinding, ...]
    redecompose_after: tuple[str, ...]
    adapter_used: bool

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "milestones": [item.to_dict() for item in self.milestones],
            "actions": [item.to_dict() for item in self.actions],
            "findings": [item.to_dict() for item in self.findings],
        }


def decompose_plan_option(
    *,
    option: PlanOption,
    horizon: GoalHorizon | None,
    existing_task_ids: tuple[str, ...] = (),
    explicit_deadlines: Mapping[str, date] | None = None,
    policy: DecompositionPolicy | None = None,
    adapter: RollingWaveAdapter | None = None,
) -> DecompositionResult:
    policy = policy or DecompositionPolicy()
    explicit_deadlines = explicit_deadlines or {}
    if len(existing_task_ids) != len(set(existing_task_ids)):
        raise DecompositionError("existing_task_ids must be unique")
    depth, window_days, action_limit = _depth_rules(option, horizon, policy)
    milestones = _normalize_waves(option.milestones)
    current = tuple(item for item in milestones if item.wave == "current")
    if not current:
        raise DecompositionError("at least one current-wave milestone is required")
    adapter_used = adapter is not None
    adapter_finding: DecompositionFinding | None = None
    if adapter is None:
        suggestions = tuple(_fallback_action(option, milestone) for milestone in current)
    else:
        try:
            suggestions = adapter.decompose(
                option=option, current_milestones=current, max_actions=action_limit
            )
        except Exception as exc:
            suggestions = tuple(_fallback_action(option, milestone) for milestone in current)
            adapter_used = False
            adapter_finding = DecompositionFinding(
                "adapter-fallback", "warning", option.option_id, str(exc)
            )
        else:
            adapter_finding = None
    if len(suggestions) > action_limit:
        raise DecompositionError(
            f"current wave contains {len(suggestions)} actions; limit is {action_limit}"
        )
    milestone_ids = {item.milestone_id for item in current}
    used_ids = set(existing_task_ids)
    generated: list[GeneratedAction] = []
    findings: list[DecompositionFinding] = []
    if adapter is not None and not adapter_used and adapter_finding is not None:
        findings.append(adapter_finding)
    for index, suggestion in enumerate(suggestions, start=1):
        if suggestion.milestone_id not in milestone_ids:
            raise DecompositionError(
                f"action references non-current milestone: {suggestion.milestone_id}"
            )
        task_id = suggestion.task_id or _stable_task_id(
            option.option_id, suggestion.milestone_id, index
        )
        if task_id in used_ids:
            raise DecompositionError(f"generated task ID collides with an existing task: {task_id}")
        used_ids.add(task_id)
        due = suggestion.due
        supported_due = explicit_deadlines.get(task_id) or explicit_deadlines.get(
            suggestion.milestone_id
        )
        if due is not None:
            if supported_due is None or due != supported_due:
                raise DecompositionError(
                    f"due date for {task_id} is not supported by an explicit constraint"
                )
        elif supported_due is not None:
            due = supported_due
        duration = suggestion.duration
        if duration is not None and duration > policy.max_action_minutes:
            findings.append(
                DecompositionFinding(
                    "action-oversized",
                    "error",
                    task_id,
                    f"Action duration exceeds {policy.max_action_minutes} minutes.",
                )
            )
        if _is_vague(suggestion.title):
            findings.append(
                DecompositionFinding(
                    "action-vague",
                    "error",
                    task_id,
                    "Action title does not describe a concrete next step.",
                )
            )
        if not suggestion.verification.strip():
            findings.append(
                DecompositionFinding(
                    "verification-missing",
                    "error",
                    task_id,
                    "Action needs visible completion evidence.",
                )
            )
        if suggestion.kind == "study-session" and _looks_like_single_flashcard(suggestion.title):
            findings.append(
                DecompositionFinding(
                    "flashcard-task-too-granular",
                    "error",
                    task_id,
                    "Flashcards must be represented as a bounded review session, not one task per card.",
                )
            )
        action = NearTermAction(
            task_id=task_id,
            title=suggestion.title,
            status="todo",
            duration=duration,
            energy=suggestion.energy,
            motivation=suggestion.motivation,
            mode=suggestion.mode,
            due=due,
            blocked_by=suggestion.blocked_by,
            milestone_id=suggestion.milestone_id,
            rationale=suggestion.rationale or "Generated for the current rolling-wave milestone.",
            source_refs=suggestion.source_refs or option.source_refs,
        )
        generated.append(
            GeneratedAction(
                action=action, verification=suggestion.verification, kind=suggestion.kind
            )
        )
    findings.extend(_duplicate_findings(generated))
    findings.extend(_blocker_findings(generated, existing_task_ids=set(existing_task_ids)))
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        codes = ", ".join(sorted({item.code for item in errors}))
        raise DecompositionError(f"generated actions failed validation: {codes}")
    checkpoints = tuple(
        f"Review {item.milestone_id} and decompose the next wave from current canonical state."
        for item in current
    )
    return DecompositionResult(
        schema_version=1,
        option_id=option.option_id,
        current_window_days=window_days,
        rolling_wave_depth=depth,
        milestones=milestones,
        actions=tuple(generated),
        findings=tuple(sorted(findings, key=lambda item: (item.severity, item.code, item.item_id))),
        redecompose_after=checkpoints,
        adapter_used=adapter_used,
    )


def _depth_rules(
    option: PlanOption, horizon: GoalHorizon | None, policy: DecompositionPolicy
) -> tuple[int, int, int]:
    if horizon == "weeks":
        depth, window, limit = 2, min(7, policy.review_window_days), min(4, policy.max_actions)
    elif horizon in {"months", "quarter"}:
        depth, window, limit = 2, policy.review_window_days, policy.max_actions
    else:
        depth, window, limit = 1, policy.review_window_days, min(5, policy.max_actions)
    if option.confidence_label == "low" or len(option.unresolved_questions) >= 2:
        limit = min(limit, 2)
        depth = 1
    return depth, window, limit


def _normalize_waves(milestones: tuple[Milestone, ...]) -> tuple[Milestone, ...]:
    if not milestones:
        raise DecompositionError("a selected option must contain at least one milestone")
    if any(item.wave == "current" for item in milestones):
        return milestones
    first = milestones[0]
    return (
        Milestone(
            milestone_id=first.milestone_id,
            title=first.title,
            outcome=first.outcome,
            status=first.status,
            wave="current",
            target_date=first.target_date,
            depends_on=first.depends_on,
        ),
        *milestones[1:],
    )


def _fallback_action(option: PlanOption, milestone: Milestone) -> ActionSuggestion:
    return ActionSuggestion(
        title=f"Define the first verifiable step for {milestone.title}",
        milestone_id=milestone.milestone_id,
        duration=20,
        energy="low",
        motivation="medium",
        mode="planning",
        rationale="A short clarification timebox avoids inventing a detailed backlog.",
        verification=f"A written next step and completion criterion for: {milestone.outcome}",
        kind="general",
        source_refs=option.source_refs,
    )


def _stable_task_id(option_id: str, milestone_id: str, index: int) -> str:
    option_slug = _slug(option_id.removeprefix("option-"))
    milestone_slug = _slug(milestone_id.removeprefix("milestone-"))
    return f"task-{option_slug}-{milestone_slug}-{index}"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:48] or "step"


def _is_vague(title: str) -> bool:
    normalized = " ".join(re.findall(r"[a-z0-9]+", title.casefold()))
    words = normalized.split()
    vague_starts = ("work on", "handle", "continue", "do task", "make progress", "deal with")
    return len(words) < 3 or any(normalized.startswith(item) for item in vague_starts)


def _looks_like_single_flashcard(title: str) -> bool:
    normalized = title.casefold()
    return "flashcard" in normalized and not any(
        word in normalized for word in ("session", "due cards", "review workload", "batch")
    )


def _duplicate_findings(actions: list[GeneratedAction]) -> list[DecompositionFinding]:
    seen: dict[str, str] = {}
    findings: list[DecompositionFinding] = []
    for item in actions:
        normalized = " ".join(re.findall(r"[a-z0-9]+", item.action.title.casefold()))
        existing = seen.get(normalized)
        if existing is not None:
            findings.append(
                DecompositionFinding(
                    "action-duplicate",
                    "error",
                    item.action.task_id,
                    f"Action duplicates {existing}.",
                )
            )
        else:
            seen[normalized] = item.action.task_id
    return findings


def _blocker_findings(
    actions: list[GeneratedAction], *, existing_task_ids: set[str]
) -> list[DecompositionFinding]:
    ids = {item.action.task_id for item in actions}
    graph: dict[str, tuple[str, ...]] = {}
    findings: list[DecompositionFinding] = []
    for item in actions:
        unknown = sorted(
            blocker
            for blocker in item.action.blocked_by
            if blocker not in ids and blocker not in existing_task_ids
        )
        if unknown:
            findings.append(
                DecompositionFinding(
                    "blocker-unknown",
                    "error",
                    item.action.task_id,
                    f"Unknown blockers: {', '.join(unknown)}",
                )
            )
        graph[item.action.task_id] = tuple(
            blocker for blocker in item.action.blocked_by if blocker in ids
        )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        cyclic = any(visit(child) for child in graph.get(node, ()))
        visiting.remove(node)
        visited.add(node)
        return cyclic

    for task_id in sorted(graph):
        if visit(task_id):
            findings.append(
                DecompositionFinding(
                    "blocker-cycle", "error", task_id, "Generated blocker graph is circular."
                )
            )
            break
    return findings
