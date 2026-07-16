"""Structured, provider-neutral plan-option synthesis and validation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, cast

from .context import PlanningContextPack
from .contracts import (
    CopilotIndex,
    GoalRecord,
    Milestone,
    PlanAssumption,
    PlanOption,
    PlanningSession,
)
from .readiness import GoalReadinessReport

OptionSetOutcome = Literal[
    "options",
    "no-viable-option",
    "experiment-first",
    "link-existing-plan",
]


class PlanOptionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PlanOptionRequest:
    schema_version: int
    goal: GoalRecord
    session: PlanningSession
    readiness: GoalReadinessReport
    context: PlanningContextPack
    existing_plan_ids: tuple[str, ...]
    as_of: date


class PlanOptionAdapter(Protocol):
    """Return zero to three visible option dictionaries under a strict contract."""

    def synthesize(self, request: PlanOptionRequest) -> tuple[Mapping[str, Any], ...]: ...


@dataclass(frozen=True, slots=True)
class DuplicatePlanFinding:
    option_id: str
    plan_id: str
    reason: str
    similarity: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanOptionSet:
    schema_version: int
    outcome: OptionSetOutcome
    options: tuple[PlanOption, ...]
    duplicate_findings: tuple[DuplicatePlanFinding, ...]
    diagnostics: tuple[str, ...]
    adapter_used: bool
    source_goal_hash: str
    context_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "options": [item.to_dict() for item in self.options],
            "duplicate_findings": [item.to_dict() for item in self.duplicate_findings],
        }


def generate_plan_options(
    *,
    goal: GoalRecord,
    session: PlanningSession,
    readiness: GoalReadinessReport,
    context: PlanningContextPack,
    index: CopilotIndex,
    as_of: date,
    adapter: PlanOptionAdapter | None = None,
) -> PlanOptionSet:
    if session.goal_ref != goal.path or session.goal_hash != goal.content_hash:
        raise PlanOptionError("planning session is stale relative to the selected goal")
    if context.goal_hash != goal.content_hash:
        raise PlanOptionError("planning context does not match the selected goal")
    if any(item.freshness == "stale" for item in context.items):
        raise PlanOptionError("planning context contains stale sources")
    if any(item.category == "hard-blocker" for item in readiness.findings):
        return _result(
            outcome="no-viable-option",
            options=(),
            diagnostics=("Goal readiness contains a hard blocker.",),
            goal=goal,
            context=context,
            adapter_used=False,
        )
    if session.decisions and session.decisions[-1].kind == "experiment":
        return _result(
            outcome="experiment-first",
            options=(),
            diagnostics=("The visible session decision selected an experiment before planning.",),
            goal=goal,
            context=context,
            adapter_used=False,
        )
    active_for_goal = tuple(
        plan
        for plan in index.plans
        if plan.status in {"active", "seed", "needs-review"}
        and plan.goal_ref is not None
        and _reference_id(plan.goal_ref) == goal.goal_id
    )
    if readiness.path == "link-existing-plan" or active_for_goal:
        return PlanOptionSet(
            schema_version=1,
            outcome="link-existing-plan",
            options=(),
            duplicate_findings=tuple(
                DuplicatePlanFinding(
                    option_id="not-generated",
                    plan_id=plan.plan_id,
                    reason="An active plan already references this goal.",
                    similarity=1.0,
                )
                for plan in sorted(active_for_goal, key=lambda item: item.plan_id)
            ),
            diagnostics=("Review the existing plan before creating another one.",),
            adapter_used=False,
            source_goal_hash=goal.content_hash,
            context_hashes=tuple(item.content_hash for item in context.items),
        )
    if not readiness.ready and not _session_answers_ready(session):
        return _result(
            outcome="no-viable-option",
            options=(),
            diagnostics=("Required clarification remains unresolved.",),
            goal=goal,
            context=context,
            adapter_used=False,
        )

    request = PlanOptionRequest(
        schema_version=1,
        goal=goal,
        session=session,
        readiness=readiness,
        context=context,
        existing_plan_ids=tuple(sorted(plan.plan_id for plan in index.plans)),
        as_of=as_of,
    )
    diagnostics: list[str] = []
    adapter_used = adapter is not None
    if adapter is None:
        options = (_deterministic_option(request),)
    else:
        try:
            raw = adapter.synthesize(request)
        except Exception as exc:
            diagnostics.append(f"adapter-fallback: {exc}")
            options = (_deterministic_option(request),)
            adapter_used = False
        else:
            if not isinstance(raw, tuple):
                raise PlanOptionError("adapter output must be a tuple")
            if len(raw) > 3:
                raise PlanOptionError("adapter returned more than three plan options")
            options = tuple(_option_from_mapping(item) for item in raw)

    _validate_option_set(options, request=request)
    duplicates = _find_duplicates(options, index=index)
    if duplicates:
        diagnostics.append("One or more options overlap an existing plan and require explicit review.")
    outcome: OptionSetOutcome = "options" if options else "no-viable-option"
    return PlanOptionSet(
        schema_version=1,
        outcome=outcome,
        options=options,
        duplicate_findings=duplicates,
        diagnostics=tuple(diagnostics),
        adapter_used=adapter_used,
        source_goal_hash=goal.content_hash,
        context_hashes=tuple(item.content_hash for item in context.items),
    )


def _result(
    *,
    outcome: OptionSetOutcome,
    options: tuple[PlanOption, ...],
    diagnostics: tuple[str, ...],
    goal: GoalRecord,
    context: PlanningContextPack,
    adapter_used: bool,
) -> PlanOptionSet:
    return PlanOptionSet(
        schema_version=1,
        outcome=outcome,
        options=options,
        duplicate_findings=(),
        diagnostics=diagnostics,
        adapter_used=adapter_used,
        source_goal_hash=goal.content_hash,
        context_hashes=tuple(item.content_hash for item in context.items),
    )


def _deterministic_option(request: PlanOptionRequest) -> PlanOption:
    goal = request.goal
    desired = goal.desired_change or _answer_value(request.session, "desired-change")
    if desired is None:
        raise PlanOptionError("deterministic fallback needs a visible desired change")
    purpose = goal.why or _answer_value(request.session, "purpose")
    boundaries = goal.non_goals or ("Do not decompose the entire long-term direction.",)
    assumptions: list[PlanAssumption] = []
    if not goal.constraints:
        assumptions.append(
            PlanAssumption(
                assumption_id="assumption-capacity-unknown",
                statement="Available capacity has not yet been confirmed.",
                source_kind="deterministic-fact",
                confidence="high",
            )
        )
    if purpose:
        assumptions.append(
            PlanAssumption(
                assumption_id="assumption-purpose-current",
                statement=f"The stated purpose remains current: {purpose}",
                source_kind="user-answer" if goal.why is None else "canonical-note",
                source_ref=goal.path,
                confidence="high",
            )
        )
    success = _answer_value(request.session, "success-evidence")
    success_evidence = (
        (success,) if success is not None else (f"Review whether this change occurred: {desired}",)
    )
    return PlanOption(
        schema_version=1,
        option_id=f"option-{goal.goal_id.removeprefix('goal-')}-focused",
        title=f"Focused first phase for {goal.title}",
        strategy="Use one bounded review cycle to create evidence before expanding scope.",
        desired_outcome=desired,
        boundaries=boundaries,
        assumptions=tuple(assumptions),
        success_evidence=success_evidence,
        risks=("The first phase may expose missing prerequisites or an unrealistic pace.",),
        review_date=None,
        milestones=(
            Milestone(
                milestone_id=f"milestone-{goal.goal_id.removeprefix('goal-')}-first-evidence",
                title="Create first reviewable evidence",
                outcome=desired,
                wave="current",
            ),
        ),
        tradeoffs=("Narrower initial scope in exchange for faster, reversible feedback.",),
        unresolved_questions=(
            () if goal.constraints else ("How much capacity is genuinely available?",)
        ),
        source_refs=tuple(item.path for item in request.context.items),
        reasons_not_fit=("It may be too structured if the direction is still exploratory.",),
        confidence_label="medium" if goal.constraints else "low",
    )


def _option_from_mapping(data: Mapping[str, Any]) -> PlanOption:
    if not isinstance(data, Mapping):
        raise PlanOptionError("every option must be a mapping")
    assumptions = tuple(
        PlanAssumption(
            assumption_id=_required_str(item, "assumption_id"),
            statement=_required_str(item, "statement"),
            source_kind=cast(Any, _required_str(item, "source_kind")),
            source_ref=_optional_str(item.get("source_ref"), "source_ref"),
            confidence=cast(Any, _required_str(item, "confidence")),
        )
        for item in _mapping_list(data.get("assumptions"), "assumptions")
    )
    milestones = tuple(
        Milestone(
            milestone_id=_required_str(item, "milestone_id"),
            title=_required_str(item, "title"),
            outcome=_required_str(item, "outcome"),
            status=_required_str(item, "status") if "status" in item else "planned",
            wave=cast(Any, _required_str(item, "wave")),
            target_date=_optional_date(item.get("target_date"), "target_date"),
            depends_on=_string_tuple(item.get("depends_on", []), "depends_on"),
        )
        for item in _mapping_list(data.get("milestones"), "milestones")
    )
    schema = data.get("schema_version")
    if type(schema) is not int:
        raise PlanOptionError("schema_version must be an integer")
    return PlanOption(
        schema_version=schema,
        option_id=_required_str(data, "option_id"),
        title=_required_str(data, "title"),
        strategy=_required_str(data, "strategy"),
        desired_outcome=_required_str(data, "desired_outcome"),
        boundaries=_string_tuple(data.get("boundaries"), "boundaries"),
        assumptions=assumptions,
        success_evidence=_string_tuple(data.get("success_evidence"), "success_evidence"),
        risks=_string_tuple(data.get("risks"), "risks"),
        review_date=_optional_date(data.get("review_date"), "review_date"),
        milestones=milestones,
        tradeoffs=_string_tuple(data.get("tradeoffs"), "tradeoffs"),
        unresolved_questions=_string_tuple(
            data.get("unresolved_questions", []), "unresolved_questions"
        ),
        source_refs=_string_tuple(data.get("source_refs"), "source_refs"),
        reasons_not_fit=_string_tuple(data.get("reasons_not_fit", []), "reasons_not_fit"),
        confidence_label=cast(Any, _required_str(data, "confidence_label")),
        rejected_alternatives=_string_tuple(
            data.get("rejected_alternatives", []), "rejected_alternatives"
        ),
    )


def _validate_option_set(
    options: tuple[PlanOption, ...], *, request: PlanOptionRequest
) -> None:
    if len(options) > 3:
        raise PlanOptionError("no more than three options are allowed")
    ids = [item.option_id for item in options]
    if len(ids) != len(set(ids)):
        raise PlanOptionError("option IDs must be unique")
    allowed_refs = {
        request.goal.goal_id,
        request.goal.path,
        *(item.path for item in request.context.items),
        *(item.source_id for item in request.context.items),
    }
    signatures: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for option in options:
        if option.review_date is not None and option.review_date < request.as_of:
            raise PlanOptionError("review dates cannot be in the past")
        unknown_refs = sorted(set(option.source_refs) - allowed_refs)
        if unknown_refs:
            raise PlanOptionError(f"option contains unknown source references: {unknown_refs}")
        signature = (
            _normalize(option.strategy),
            tuple(sorted(_normalize(item) for item in option.boundaries)),
            tuple(sorted(_normalize(item) for item in option.tradeoffs)),
        )
        if signature in signatures:
            raise PlanOptionError("multiple options are cosmetic rewrites rather than distinct strategies")
        signatures.add(signature)
        for assumption in option.assumptions:
            if assumption.source_ref is not None and assumption.source_ref not in allowed_refs:
                raise PlanOptionError(
                    f"assumption contains unknown source reference: {assumption.source_ref}"
                )


def _find_duplicates(
    options: tuple[PlanOption, ...], *, index: CopilotIndex
) -> tuple[DuplicatePlanFinding, ...]:
    findings: list[DuplicatePlanFinding] = []
    for option in options:
        option_tokens = _tokens(f"{option.title} {option.desired_outcome}")
        for plan in index.plans:
            plan_tokens = _tokens(f"{plan.title} {plan.desired_outcome or ''}")
            similarity = _jaccard(option_tokens, plan_tokens)
            if similarity >= 0.55:
                findings.append(
                    DuplicatePlanFinding(
                        option_id=option.option_id,
                        plan_id=plan.plan_id,
                        reason="Title and desired outcome substantially overlap an existing plan.",
                        similarity=round(similarity, 3),
                    )
                )
    return tuple(
        sorted(findings, key=lambda item: (item.option_id, -item.similarity, item.plan_id))
    )


def _session_answers_ready(session: PlanningSession) -> bool:
    answered = {item.question_id for item in session.answers if item.response_kind == "answered"}
    return {"purpose", "desired-change", "horizon"} <= answered


def _answer_value(session: PlanningSession, question_id: str) -> str | None:
    for answer in session.answers:
        if answer.question_id == question_id and answer.response_kind == "answered":
            return answer.value
    return None


def _reference_id(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("[[") and cleaned.endswith("]]" ):
        cleaned = cleaned[2:-2].split("|", 1)[0]
    return Path(cleaned).stem


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _mapping_list(value: object, name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PlanOptionError(f"{name} must be a list of mappings")
    return cast(list[Mapping[str, Any]], value)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise PlanOptionError(f"{name} must be a list of non-empty strings")
    return tuple(cast(list[str], value))


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PlanOptionError(f"{key} must be a trimmed non-empty string")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PlanOptionError(f"{name} must be a non-empty string or null")
    return value


def _optional_date(value: object, name: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PlanOptionError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PlanOptionError(f"{name} must be an ISO date") from exc
