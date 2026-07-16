"""Read-only facade for deterministic copilot diagnostics and context preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lifeos.copilot import build_copilot_index, parse_goal_note
from lifeos.copilot.context import (
    PlanningContextPack,
    PlanningContextPolicy,
    build_planning_context,
)
from lifeos.copilot.readiness import GoalReadinessReport, evaluate_goal_readiness
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.vault import read_vault_markdown

COPILOT_READINESS_DESCRIPTOR = ToolDescriptor(
    name="copilot.goal_readiness",
    description="Inspect deterministic readiness findings for one canonical goal.",
    effect=ToolEffect.READ_ONLY,
)
COPILOT_CONTEXT_DESCRIPTOR = ToolDescriptor(
    name="copilot.context_preview",
    description="Build a bounded, inspectable planning context preview.",
    effect=ToolEffect.READ_ONLY,
)


@dataclass(frozen=True, slots=True)
class CopilotReadinessRequest:
    goal_path: str


@dataclass(frozen=True, slots=True)
class CopilotContextRequest:
    goal_path: str
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    redact_terms: tuple[str, ...] = ()
    allowed_sensitive_roots: tuple[str, ...] = ()
    max_total_bytes: int = 24_000
    max_item_bytes: int = 6_000


def inspect_goal_readiness(
    *, vault_root: Path, request: CopilotReadinessRequest
) -> GoalReadinessReport:
    source = read_vault_markdown(vault_root, request.goal_path)
    goal = parse_goal_note(path=request.goal_path, content=source.content)
    return evaluate_goal_readiness(goal, index=build_copilot_index(vault_root))


def preview_goal_context(
    *, vault_root: Path, request: CopilotContextRequest
) -> PlanningContextPack:
    source = read_vault_markdown(vault_root, request.goal_path)
    goal = parse_goal_note(path=request.goal_path, content=source.content)
    return build_planning_context(
        vault_root=vault_root,
        goal=goal,
        index=build_copilot_index(vault_root),
        include_paths=request.include_paths,
        exclude_paths=request.exclude_paths,
        redact_terms=request.redact_terms,
        policy=PlanningContextPolicy(
            allowed_sensitive_roots=request.allowed_sensitive_roots
        ),
        max_total_bytes=request.max_total_bytes,
        max_item_bytes=request.max_item_bytes,
    )

from datetime import date
from typing import Mapping

from lifeos.copilot.capacity import (
    PortfolioCapacityReport,
    RecurringWorkload,
    check_portfolio_capacity,
)
from lifeos.copilot.decomposition import DecompositionResult
from lifeos.copilot.contracts import PlanOption

COPILOT_CAPACITY_DESCRIPTOR = ToolDescriptor(
    name="copilot.capacity_check",
    description="Compare one draft plan with visible portfolio capacity and conflicts.",
    effect=ToolEffect.READ_ONLY,
)


@dataclass(frozen=True, slots=True)
class CopilotCapacityRequest:
    option: PlanOption
    decomposition: DecompositionResult
    available_minutes: int | None
    recurring_workloads: tuple[RecurringWorkload, ...] = ()
    adaptive_durations: Mapping[str, int | None] | None = None
    as_of: date = date.today()


def inspect_portfolio_capacity(
    *, vault_root: Path, request: CopilotCapacityRequest
) -> PortfolioCapacityReport:
    return check_portfolio_capacity(
        option=request.option,
        decomposition=request.decomposition,
        index=build_copilot_index(vault_root),
        as_of=request.as_of,
        available_minutes=request.available_minutes,
        recurring_workloads=request.recurring_workloads,
        adaptive_durations=request.adaptive_durations,
    )

from lifeos.copilot.explanations import (
    CounterfactualResult,
    PlanExplanation,
    PlanOptionComparison,
    compare_plan_options,
    explain_plan_option,
    recompute_capacity_counterfactual,
)

COPILOT_EXPLAIN_DESCRIPTOR = ToolDescriptor(
    name="copilot.explain",
    description="Explain one draft option using inspectable provenance and omissions.",
    effect=ToolEffect.READ_ONLY,
)
COPILOT_COMPARE_DESCRIPTOR = ToolDescriptor(
    name="copilot.compare",
    description="Compare up to three options across explicit planning dimensions.",
    effect=ToolEffect.READ_ONLY,
)


def explain_copilot_option(
    *, option: PlanOption, decomposition: DecompositionResult,
    capacity: PortfolioCapacityReport, context: PlanningContextPack,
) -> PlanExplanation:
    return explain_plan_option(
        option=option, decomposition=decomposition, capacity=capacity, context=context
    )


def compare_copilot_options(
    *, options: tuple[PlanOption, ...],
    decompositions: Mapping[str, DecompositionResult],
    capacity_reports: Mapping[str, PortfolioCapacityReport],
) -> PlanOptionComparison:
    return compare_plan_options(
        options=options, decompositions=decompositions, capacity_reports=capacity_reports
    )


def counterfactual_capacity(
    *, vault_root: Path, option: PlanOption, decomposition: DecompositionResult,
    before: PortfolioCapacityReport, as_of: date, available_minutes: int | None,
) -> CounterfactualResult:
    return recompute_capacity_counterfactual(
        option=option, decomposition=decomposition, index=build_copilot_index(vault_root),
        before=before, as_of=as_of, available_minutes=available_minutes,
    )


from lifeos.copilot.replanning import (
    ReplanningProposalRequest,
    ReplanningProposalResult,
    ReplanningReview,
    ReplanningTrigger,
    ReviewEvidence,
    build_replanning_review,
    create_replanning_proposal,
    scan_replanning_triggers,
)

COPILOT_REPLANNING_SCAN_DESCRIPTOR = ToolDescriptor(
    name="copilot.replanning_scan",
    description="Find evidence-backed goal and plan review entry points.",
    effect=ToolEffect.READ_ONLY,
)
COPILOT_REPLANNING_REVIEW_DESCRIPTOR = ToolDescriptor(
    name="copilot.replanning_review",
    description="Compare current canonical planning state with explicit review evidence.",
    effect=ToolEffect.READ_ONLY,
)
COPILOT_REPLANNING_PROPOSAL_DESCRIPTOR = ToolDescriptor(
    name="copilot.replanning_proposal",
    description="Create a reviewable proposal for a selected replanning outcome.",
    effect=ToolEffect.PROPOSAL_PRODUCING,
)


@dataclass(frozen=True, slots=True)
class CopilotReplanningReviewRequest:
    target_path: str
    as_of: date
    expected_hash: str | None = None
    corrections: tuple[ReviewEvidence, ...] = ()
    recent_answers: tuple[ReviewEvidence, ...] = ()


def scan_copilot_replanning(
    *, vault_root: Path, runtime_dir: Path, as_of: date
) -> tuple[ReplanningTrigger, ...]:
    return scan_replanning_triggers(
        vault_root=vault_root, runtime_dir=runtime_dir, as_of=as_of
    )


def inspect_copilot_replanning(
    *, vault_root: Path, runtime_dir: Path, request: CopilotReplanningReviewRequest
) -> ReplanningReview:
    return build_replanning_review(
        vault_root=vault_root,
        runtime_dir=runtime_dir,
        target_path=request.target_path,
        as_of=request.as_of,
        expected_hash=request.expected_hash,
        corrections=request.corrections,
        recent_answers=request.recent_answers,
    )


def propose_copilot_replanning(
    *, vault_root: Path, request: ReplanningProposalRequest, actor_id: str
) -> ReplanningProposalResult | None:
    return create_replanning_proposal(
        vault_root=vault_root, request=request, actor_id=actor_id
    )
