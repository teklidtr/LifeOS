"""Goal-to-plan copilot contracts and services."""

from .contracts import (
    CURRENT_COPILOT_SCHEMA_VERSION,
    ContractDiagnostic,
    CopilotContractError,
    CopilotIndex,
    GoalRecord,
    Milestone,
    NearTermAction,
    PlanAssumption,
    PlanOption,
    PlanRecord,
    PlanningAnswer,
    PlanningDecision,
    PlanningSession,
    SourceReference,
    build_copilot_index,
    compatibility_diagnostics,
    content_hash,
    inspect_copilot_note,
    parse_goal_note,
    parse_plan_note,
)

__all__ = [
    "CURRENT_COPILOT_SCHEMA_VERSION",
    "ContractDiagnostic",
    "CopilotContractError",
    "CopilotIndex",
    "GoalRecord",
    "Milestone",
    "NearTermAction",
    "PlanAssumption",
    "PlanOption",
    "PlanRecord",
    "PlanningAnswer",
    "PlanningDecision",
    "PlanningSession",
    "SourceReference",
    "build_copilot_index",
    "compatibility_diagnostics",
    "content_hash",
    "inspect_copilot_note",
    "parse_goal_note",
    "parse_plan_note",
]

from .context import (
    ContextOmission,
    ContextRedaction,
    PlanningContextError,
    PlanningContextItem,
    PlanningContextPack,
    PlanningContextPolicy,
    build_planning_context,
)
from .readiness import (
    GoalReadinessReport,
    ReadinessFinding,
    evaluate_goal_readiness,
)

__all__ += [
    "ContextOmission",
    "ContextRedaction",
    "PlanningContextError",
    "PlanningContextItem",
    "PlanningContextPack",
    "PlanningContextPolicy",
    "build_planning_context",
    "GoalReadinessReport",
    "ReadinessFinding",
    "evaluate_goal_readiness",
]
