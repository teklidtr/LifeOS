"""Inspectable explanations, provenance, comparisons, and counterfactuals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Mapping, Sequence

from .capacity import PortfolioCapacityReport, RecurringWorkload, check_portfolio_capacity
from .context import PlanningContextPack
from .contracts import CopilotIndex, PlanOption, SourceKind
from .decomposition import DecompositionResult


class ExplanationError(ValueError):
    """Raised when an explanation would cite an invalid or opaque source."""


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    field_path: str
    source_kind: SourceKind
    source_ref: str | None
    statement: str
    evidence_state: Literal["supported", "assumption", "missing", "stale", "excluded", "deleted"]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ItemExplanation:
    item_id: str
    item_kind: Literal["option", "milestone", "action", "capacity-finding"]
    summary: str
    provenance: tuple[ProvenanceEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "provenance": [item.to_dict() for item in self.provenance]}


@dataclass(frozen=True, slots=True)
class ContradictionSummary:
    code: str
    statement: str
    refs: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OmissionSummary:
    path: str
    reason: str
    effect: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlanExplanation:
    schema_version: int
    option_id: str
    summary: str
    items: tuple[ItemExplanation, ...]
    contradictions: tuple[ContradictionSummary, ...]
    omissions: tuple[OmissionSummary, ...]
    capacity_views: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "items": [item.to_dict() for item in self.items],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "omissions": [item.to_dict() for item in self.omissions],
        }


@dataclass(frozen=True, slots=True)
class ComparisonDimension:
    dimension: Literal["scope", "pace", "uncertainty", "capacity-fit", "risks", "reversible-first-step", "unresolved-questions"]
    values: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {"dimension": self.dimension, "values": [{"option_id": key, "value": value} for key, value in self.values]}


@dataclass(frozen=True, slots=True)
class PlanOptionComparison:
    schema_version: int
    option_ids: tuple[str, ...]
    dimensions: tuple[ComparisonDimension, ...]
    criteria_note: str

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "dimensions": [item.to_dict() for item in self.dimensions]}


@dataclass(frozen=True, slots=True)
class CounterfactualResult:
    schema_version: int
    option_id: str
    change: str
    before_fit: str
    after_fit: str
    changed_findings: tuple[str, ...]
    report: PortfolioCapacityReport

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "report": self.report.to_dict()}


def explain_plan_option(
    *,
    option: PlanOption,
    decomposition: DecompositionResult,
    capacity: PortfolioCapacityReport,
    context: PlanningContextPack,
) -> PlanExplanation:
    if option.option_id != decomposition.option_id or option.option_id != capacity.option_id:
        raise ExplanationError("option, decomposition, and capacity report must match")
    sources = _source_states(context)
    option_provenance: list[ProvenanceEntry] = []
    for ref in option.source_refs:
        option_provenance.append(_entry("option.source_refs", "canonical-note", ref, "This source informed the visible option.", sources))
    for assumption in option.assumptions:
        state = "assumption" if assumption.source_kind == "agent-assumption" else None
        option_provenance.append(_entry(
            f"option.assumptions.{assumption.assumption_id}", assumption.source_kind,
            assumption.source_ref, assumption.statement, sources, forced_state=state,
        ))
    if not option_provenance:
        option_provenance.append(ProvenanceEntry("option", "deterministic-fact", None, "No supporting source was attached to this sparse option.", "missing"))

    items: list[ItemExplanation] = [ItemExplanation(
        option.option_id, "option", f"{option.title}: {option.strategy}", tuple(sorted(option_provenance, key=_provenance_key))
    )]
    for milestone in sorted(option.milestones, key=lambda item: item.milestone_id):
        provenance = tuple(_entry(
            f"milestones.{milestone.milestone_id}", "deterministic-fact", ref,
            "The milestone is part of the selected rolling-wave option.", sources,
        ) for ref in option.source_refs) or (ProvenanceEntry(f"milestones.{milestone.milestone_id}", "deterministic-fact", None, "Generated from the visible option structure.", "supported"),)
        items.append(ItemExplanation(milestone.milestone_id, "milestone", milestone.outcome, provenance))
    for generated in sorted(decomposition.actions, key=lambda item: item.action.task_id):
        action = generated.action
        refs = action.source_refs or option.source_refs
        provenance = tuple(_entry(
            f"actions.{action.task_id}", "deterministic-fact", ref,
            action.rationale or "Generated for the current rolling-wave milestone.", sources,
        ) for ref in refs) or (ProvenanceEntry(f"actions.{action.task_id}", "deterministic-fact", None, action.rationale or "Generated from the selected milestone.", "supported"),)
        items.append(ItemExplanation(action.task_id, "action", f"{action.title}. Evidence: {generated.verification}", provenance))
    for finding in capacity.findings:
        provenance = tuple(ProvenanceEntry(
            f"capacity.{finding.code}", "deterministic-fact", ref,
            "This visible input contributed to the capacity finding.", "supported",
        ) for ref in finding.evidence_refs) or (ProvenanceEntry(f"capacity.{finding.code}", "deterministic-fact", None, "The finding is based on missing or aggregate visible inputs.", "missing" if finding.missingness else "supported"),)
        items.append(ItemExplanation(finding.code, "capacity-finding", finding.title, provenance))

    contradictions = _contradictions(option, capacity)
    omissions = tuple(OmissionSummary(item.path, item.reason, _omission_effect(item.reason)) for item in context.omissions)
    views = (f"Baseline fit: {capacity.baseline.fit}.",) + ((f"Adaptive fit: {capacity.adaptive.fit}.",) if capacity.adaptive else ())
    return PlanExplanation(
        1, option.option_id,
        "Explanation cites visible notes, answers, assumptions, deterministic rules, and optional adaptive evidence. It does not expose hidden reasoning.",
        tuple(items), contradictions, omissions, views,
    )


def compare_plan_options(
    *,
    options: Sequence[PlanOption],
    decompositions: Mapping[str, DecompositionResult],
    capacity_reports: Mapping[str, PortfolioCapacityReport],
) -> PlanOptionComparison:
    ordered = tuple(sorted(options, key=lambda item: item.option_id))
    if not 1 <= len(ordered) <= 3:
        raise ExplanationError("comparison requires one to three options")
    for option in ordered:
        if option.option_id not in decompositions or option.option_id not in capacity_reports:
            raise ExplanationError(f"missing comparison data for {option.option_id}")
    dimensions: tuple[ComparisonDimension, ...] = (
        _dimension("scope", ordered, lambda o: f"{len(o.milestones)} milestones; {len(decompositions[o.option_id].actions)} near-term actions"),
        _dimension("pace", ordered, lambda o: f"{decompositions[o.option_id].current_window_days}-day current window"),
        _dimension("uncertainty", ordered, lambda o: f"{o.confidence_label} confidence; {len(o.assumptions)} assumptions"),
        _dimension("capacity-fit", ordered, lambda o: capacity_reports[o.option_id].fit),
        _dimension("risks", ordered, lambda o: "; ".join(o.risks) or "No stated risks"),
        _dimension("reversible-first-step", ordered, lambda o: decompositions[o.option_id].actions[0].action.title if decompositions[o.option_id].actions else "No feasible first step"),
        _dimension("unresolved-questions", ordered, lambda o: "; ".join(o.unresolved_questions) or "None"),
    )
    return PlanOptionComparison(1, tuple(item.option_id for item in ordered), dimensions, "No winner is assigned. Compare the visible dimensions against your own criteria.")


def recompute_capacity_counterfactual(
    *,
    option: PlanOption,
    decomposition: DecompositionResult,
    index: CopilotIndex,
    before: PortfolioCapacityReport,
    as_of: date,
    available_minutes: int | None,
    recurring_workloads: Sequence[RecurringWorkload] | None = None,
    adaptive_durations: Mapping[str, int | None] | None = None,
) -> CounterfactualResult:
    after = check_portfolio_capacity(
        option=option, decomposition=decomposition, index=index, as_of=as_of,
        available_minutes=available_minutes,
        recurring_workloads=before.recurring_workloads if recurring_workloads is None else recurring_workloads,
        adaptive_durations=adaptive_durations,
    )
    before_codes = {item.code for item in before.findings}
    after_codes = {item.code for item in after.findings}
    change = f"Available capacity changed from {before.baseline.available_minutes} to {available_minutes} minutes."
    return CounterfactualResult(1, option.option_id, change, before.fit, after.fit, tuple(sorted(before_codes ^ after_codes)), after)


def _source_states(context: PlanningContextPack) -> dict[str, Literal["supported", "stale", "excluded", "deleted"]]:
    result: dict[str, Literal["supported", "stale", "excluded", "deleted"]] = {}
    for item in context.items:
        state: Literal["supported", "stale"] = "stale" if item.freshness == "stale" else "supported"
        result[item.path] = state
        result[item.source_id] = state
    for omission in context.omissions:
        result[omission.path] = "excluded" if "excluded" in omission.reason or "denied" in omission.reason else "deleted"
    return result


def _entry(field_path: str, source_kind: SourceKind, source_ref: str | None, statement: str, sources: Mapping[str, str], forced_state: str | None = None) -> ProvenanceEntry:
    if source_ref is None:
        state = forced_state or ("assumption" if source_kind == "agent-assumption" else "supported")
    elif source_ref not in sources:
        raise ExplanationError(f"invalid explanation source reference: {source_ref}")
    else:
        state = forced_state or sources[source_ref]
    return ProvenanceEntry(field_path, source_kind, source_ref, statement, state)  # type: ignore[arg-type]


def _contradictions(option: PlanOption, capacity: PortfolioCapacityReport) -> tuple[ContradictionSummary, ...]:
    findings: list[ContradictionSummary] = []
    capacity_assumptions = [a for a in option.assumptions if "capacity" in a.statement.casefold()]
    if capacity.fit == "overload" and capacity_assumptions:
        findings.append(ContradictionSummary("capacity-assumption-conflict", "A visible capacity assumption conflicts with the current overload finding.", tuple(a.assumption_id for a in capacity_assumptions)))
    if option.review_date and any(m.target_date and m.target_date > option.review_date for m in option.milestones):
        findings.append(ContradictionSummary("review-before-milestone", "The plan review occurs before a stated milestone target.", tuple(m.milestone_id for m in option.milestones if m.target_date and m.target_date > option.review_date)))
    return tuple(sorted(findings, key=lambda item: item.code))


def _omission_effect(reason: str) -> str:
    if "sensitive" in reason:
        return "Potentially relevant sensitive context was intentionally not used."
    if "excluded" in reason:
        return "The user excluded this source, so related claims may be less supported."
    if "budget" in reason:
        return "The context limit prevented this source from informing the draft."
    return "The source was unavailable and did not inform the draft."


def _dimension(name: str, options: Sequence[PlanOption], render) -> ComparisonDimension:
    return ComparisonDimension(name, tuple((option.option_id, render(option)) for option in options))  # type: ignore[arg-type]


def _provenance_key(item: ProvenanceEntry) -> tuple[str, str, str]:
    return item.field_path, item.source_kind, item.source_ref or ""
