"""Deterministic portfolio-capacity and conflict checks for draft plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Mapping, Sequence

from .contracts import CopilotIndex, NearTermAction, PlanOption, PlanRecord
from .decomposition import DecompositionResult

FitLabel = Literal["comfortable", "marginal", "overload", "unknown"]
FindingSeverity = Literal["information", "warning", "high"]
WorkloadKind = Literal[
    "study", "routine", "exercise", "diet", "rest", "relationship", "hobby", "other"
]


class CapacityError(ValueError):
    """Raised when explicit capacity inputs are malformed."""


@dataclass(frozen=True, slots=True)
class RecurringWorkload:
    workload_id: str
    title: str
    minutes: int | None
    kind: WorkloadKind = "other"
    protected: bool = True
    source_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.workload_id.strip() or not self.title.strip():
            raise CapacityError("workload_id and title are required")
        if self.minutes is not None and (type(self.minutes) is not int or self.minutes < 0):
            raise CapacityError("workload minutes must be a non-negative integer or unknown")
        if self.kind not in {
            "study",
            "routine",
            "exercise",
            "diet",
            "rest",
            "relationship",
            "hobby",
            "other",
        }:
            raise CapacityError("unsupported recurring workload kind")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapacityView:
    label: Literal["baseline", "adaptive"]
    available_minutes: int | None
    protected_minutes: int | None
    existing_minutes: int | None
    proposed_minutes: int | None
    remaining_minutes: int | None
    fit: FitLabel
    unknown_duration_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapacityFinding:
    code: str
    severity: FindingSeverity
    title: str
    evidence_refs: tuple[str, ...]
    missingness: tuple[str, ...] = ()
    possible_adjustments: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PortfolioCapacityReport:
    schema_version: int
    option_id: str
    baseline: CapacityView
    adaptive: CapacityView | None
    active_plan_ids: tuple[str, ...]
    recurring_workloads: tuple[RecurringWorkload, ...]
    findings: tuple[CapacityFinding, ...]
    alternatives: tuple[str, ...]
    generated_as_of: date

    @property
    def fit(self) -> FitLabel:
        return self.adaptive.fit if self.adaptive is not None else self.baseline.fit

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "baseline": self.baseline.to_dict(),
            "adaptive": self.adaptive.to_dict() if self.adaptive else None,
            "recurring_workloads": [item.to_dict() for item in self.recurring_workloads],
            "findings": [item.to_dict() for item in self.findings],
            "generated_as_of": self.generated_as_of.isoformat(),
            "fit": self.fit,
        }


def check_portfolio_capacity(
    *,
    option: PlanOption,
    decomposition: DecompositionResult,
    index: CopilotIndex,
    as_of: date,
    available_minutes: int | None,
    recurring_workloads: Sequence[RecurringWorkload] = (),
    adaptive_durations: Mapping[str, int | None] | None = None,
    active_plan_limit: int = 5,
) -> PortfolioCapacityReport:
    """Compare a draft against visible commitments without producing a life score."""
    if decomposition.option_id != option.option_id:
        raise CapacityError("decomposition does not belong to the selected option")
    if available_minutes is not None and (
        type(available_minutes) is not int or available_minutes < 0
    ):
        raise CapacityError("available_minutes must be non-negative or unknown")
    if type(active_plan_limit) is not int or active_plan_limit < 1:
        raise CapacityError("active_plan_limit must be a positive integer")

    workloads = tuple(sorted(recurring_workloads, key=lambda item: item.workload_id))
    active = tuple(
        sorted(
            (p for p in index.plans if p.status in {"active", "seed", "needs-review"}),
            key=lambda item: item.plan_id,
        )
    )
    proposed = tuple(item.action for item in decomposition.actions)
    existing = tuple(
        action
        for plan in active
        for action in plan.tasks
        if action.status not in {"done", "cancelled"}
    )

    protected, workload_unknown = _sum_known(
        tuple((item.workload_id, item.minutes) for item in workloads if item.protected)
    )
    baseline_existing, existing_unknown = _sum_actions(existing, overrides=None)
    baseline_proposed, proposed_unknown = _sum_actions(proposed, overrides=None)
    baseline = _view(
        label="baseline",
        available=available_minutes,
        protected=protected if not workload_unknown else None,
        existing=baseline_existing,
        proposed=baseline_proposed,
        unknown=tuple(sorted((*workload_unknown, *existing_unknown, *proposed_unknown))),
    )

    adaptive: CapacityView | None = None
    if adaptive_durations is not None:
        normalized = _normalize_adaptive(adaptive_durations)
        adaptive_existing, adaptive_existing_unknown = _sum_actions(existing, normalized)
        adaptive_proposed, adaptive_proposed_unknown = _sum_actions(proposed, normalized)
        adaptive = _view(
            label="adaptive",
            available=available_minutes,
            protected=protected if not workload_unknown else None,
            existing=adaptive_existing,
            proposed=adaptive_proposed,
            unknown=tuple(
                sorted((*workload_unknown, *adaptive_existing_unknown, *adaptive_proposed_unknown))
            ),
        )

    findings: list[CapacityFinding] = []
    effective = adaptive or baseline
    if effective.fit == "overload":
        findings.append(
            _finding(
                "capacity-overload",
                "high",
                "The visible commitments exceed stated capacity.",
                refs=tuple(item.task_id for item in proposed),
                adjustments=(
                    "Reduce the first-wave scope.",
                    "Extend the horizon.",
                    "Pause a selected existing plan.",
                    "Keep this goal unplanned for now.",
                ),
            )
        )
    elif effective.fit == "marginal":
        findings.append(
            _finding(
                "capacity-marginal",
                "warning",
                "The draft leaves little visible capacity for variation.",
                refs=tuple(item.task_id for item in proposed),
                adjustments=(
                    "Run a shorter experiment.",
                    "Reduce the number of near-term actions.",
                ),
            )
        )
    elif effective.fit == "unknown":
        findings.append(
            _finding(
                "capacity-unknown",
                "information",
                "Capacity fit cannot be determined from the visible data.",
                refs=(),
                missing=effective.unknown_duration_ids or ("available_minutes",),
                adjustments=(
                    "Add a rough capacity range.",
                    "Proceed as a bounded experiment.",
                    "Keep the goal unplanned.",
                ),
            )
        )

    if len(active) > active_plan_limit:
        findings.append(
            _finding(
                "active-plan-count-high",
                "warning",
                f"There are {len(active)} active or review-needed plans.",
                refs=tuple(plan.path for plan in active),
                adjustments=(
                    "Review active-plan status before adding another plan.",
                    "Link this goal to an existing plan.",
                ),
            )
        )
    findings.extend(_due_date_findings(proposed, existing, available_minutes))
    findings.extend(_prerequisite_findings(proposed, existing))
    findings.extend(_duplicate_outcome_findings(option, active))
    if proposed and all(action.blocked_by for action in proposed):
        findings.append(
            _finding(
                "no-feasible-next-action",
                "high",
                "Every proposed near-term action has a visible blocker.",
                refs=tuple(action.task_id for action in proposed),
                adjustments=(
                    "Add an unblocked prerequisite action.",
                    "Run a prerequisite experiment.",
                    "Keep the goal unplanned.",
                ),
            )
        )
    if not workloads:
        findings.append(
            _finding(
                "recurring-workload-data-missing",
                "information",
                "No recurring workload data was supplied.",
                refs=(),
                missing=("recurring_workloads",),
                adjustments=("Preview routines and protected commitments before approval.",),
            )
        )
    if adaptive is not None and adaptive.fit != baseline.fit:
        findings.append(
            _finding(
                "baseline-adaptive-difference",
                "information",
                "Baseline and adaptive estimates produce different fit labels.",
                refs=tuple(sorted(adaptive_durations or {})),
                adjustments=("Inspect both views and choose which evidence to trust.",),
            )
        )

    ordered = tuple(
        sorted(
            findings,
            key=lambda item: (_severity_rank(item.severity), item.code, item.evidence_refs),
        )
    )
    alternatives = _alternatives(ordered, effective.fit)
    return PortfolioCapacityReport(
        schema_version=1,
        option_id=option.option_id,
        baseline=baseline,
        adaptive=adaptive,
        active_plan_ids=tuple(plan.plan_id for plan in active),
        recurring_workloads=workloads,
        findings=ordered,
        alternatives=alternatives,
        generated_as_of=as_of,
    )


def _view(
    *,
    label: Literal["baseline", "adaptive"],
    available: int | None,
    protected: int | None,
    existing: int | None,
    proposed: int | None,
    unknown: tuple[str, ...],
) -> CapacityView:
    if available is None or protected is None or existing is None or proposed is None:
        remaining = None
        fit: FitLabel = "unknown"
    else:
        remaining = available - protected - existing - proposed
        used = protected + existing + proposed
        if used > available:
            fit = "overload"
        elif remaining <= max(30, int(available * 0.1)):
            fit = "marginal"
        else:
            fit = "comfortable"
    return CapacityView(label, available, protected, existing, proposed, remaining, fit, unknown)


def _sum_actions(
    actions: Sequence[NearTermAction], overrides: Mapping[str, int | None] | None
) -> tuple[int | None, tuple[str, ...]]:
    values = tuple(
        (
            item.task_id,
            overrides.get(item.task_id, item.duration) if overrides is not None else item.duration,
        )
        for item in actions
    )
    return _sum_known(values)


def _sum_known(values: Sequence[tuple[str, int | None]]) -> tuple[int | None, tuple[str, ...]]:
    missing = tuple(sorted(identifier for identifier, value in values if value is None))
    if missing:
        return None, missing
    return sum(value or 0 for _, value in values), ()


def _normalize_adaptive(values: Mapping[str, int | None]) -> dict[str, int | None]:
    normalized: dict[str, int | None] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key.strip():
            raise CapacityError("adaptive duration IDs must be non-empty strings")
        if value is not None and (type(value) is not int or value < 1 or value > 1440):
            raise CapacityError("adaptive durations must be 1..1440 minutes or unknown")
        normalized[key] = value
    return normalized


def _due_date_findings(
    proposed: Sequence[NearTermAction], existing: Sequence[NearTermAction], available: int | None
) -> list[CapacityFinding]:
    grouped: dict[date, list[NearTermAction]] = {}
    for action in (*proposed, *existing):
        if action.due is not None:
            grouped.setdefault(action.due, []).append(action)
    findings: list[CapacityFinding] = []
    for due, actions in sorted(grouped.items()):
        if len(actions) < 2:
            continue
        known = [item.duration for item in actions if item.duration is not None]
        severity: FindingSeverity = (
            "high"
            if available is not None and len(known) == len(actions) and sum(known) > available
            else "warning"
        )
        findings.append(
            _finding(
                "due-date-contention",
                severity,
                f"Multiple visible actions converge on {due.isoformat()}.",
                refs=tuple(sorted(item.task_id for item in actions)),
                missing=tuple(sorted(item.task_id for item in actions if item.duration is None)),
                adjustments=(
                    "Move one deadline if it is not externally fixed.",
                    "Reduce the current wave.",
                ),
            )
        )
    return findings


def _prerequisite_findings(
    proposed: Sequence[NearTermAction], existing: Sequence[NearTermAction]
) -> list[CapacityFinding]:
    owners: dict[str, set[str]] = {}
    for action in (*proposed, *existing):
        for blocker in action.blocked_by:
            owners.setdefault(blocker, set()).add(action.task_id)
    return [
        _finding(
            "competing-prerequisite",
            "warning",
            f"Several actions depend on {blocker}.",
            refs=(blocker, *tuple(sorted(dependents))),
            adjustments=(
                "Complete or validate the shared prerequisite first.",
                "Sequence the dependent actions.",
            ),
        )
        for blocker, dependents in sorted(owners.items())
        if len(dependents) > 1
    ]


def _duplicate_outcome_findings(
    option: PlanOption, plans: Sequence[PlanRecord]
) -> list[CapacityFinding]:
    option_tokens = _tokens(option.desired_outcome)
    findings: list[CapacityFinding] = []
    for plan in plans:
        if not plan.desired_outcome:
            continue
        other = _tokens(plan.desired_outcome)
        union = option_tokens | other
        similarity = len(option_tokens & other) / len(union) if union else 0.0
        if similarity >= 0.55:
            findings.append(
                _finding(
                    "duplicate-outcome",
                    "warning",
                    f"The draft overlaps the visible outcome of {plan.plan_id}.",
                    refs=(option.option_id, plan.path),
                    adjustments=(
                        "Link the goal to the existing plan.",
                        "Narrow the new plan to a distinct outcome.",
                    ),
                )
            )
    return findings


def _tokens(value: str) -> set[str]:
    return {
        token.strip(".,:;!?()[]{}").casefold()
        for token in value.split()
        if len(token.strip(".,:;!?()[]{}")) > 2
    }


def _finding(
    code: str,
    severity: FindingSeverity,
    title: str,
    *,
    refs: tuple[str, ...],
    missing: tuple[str, ...] = (),
    adjustments: tuple[str, ...] = (),
) -> CapacityFinding:
    return CapacityFinding(
        code, severity, title, tuple(sorted(set(refs))), tuple(sorted(set(missing))), adjustments
    )


def _severity_rank(value: FindingSeverity) -> int:
    return {"high": 0, "warning": 1, "information": 2}[value]


def _alternatives(findings: Sequence[CapacityFinding], fit: FitLabel) -> tuple[str, ...]:
    values = {adjustment for finding in findings for adjustment in finding.possible_adjustments}
    if fit == "comfortable":
        values.add("Proceed with the bounded first wave and review before expanding.")
    values.add("Keep the goal unplanned for now.")
    return tuple(sorted(values))
