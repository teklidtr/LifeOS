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

from .sessions import (
    ClarificationQuestion,
    ClarificationQuestionAdapter,
    PlanningSessionError,
    PlanningSessionService,
    QuestionSuggestion,
    SessionConflictError,
    SessionEnvelope,
    SessionSnapshot,
)

__all__ += [
    "ClarificationQuestion",
    "ClarificationQuestionAdapter",
    "PlanningSessionError",
    "PlanningSessionService",
    "QuestionSuggestion",
    "SessionConflictError",
    "SessionEnvelope",
    "SessionSnapshot",
]

from .options import (
    DuplicatePlanFinding,
    PlanOptionAdapter,
    PlanOptionError,
    PlanOptionRequest,
    PlanOptionSet,
    generate_plan_options,
)

__all__ += [
    "DuplicatePlanFinding",
    "PlanOptionAdapter",
    "PlanOptionError",
    "PlanOptionRequest",
    "PlanOptionSet",
    "generate_plan_options",
]

from .decomposition import (
    ActionSuggestion,
    DecompositionError,
    DecompositionFinding,
    DecompositionPolicy,
    DecompositionResult,
    GeneratedAction,
    RollingWaveAdapter,
    decompose_plan_option,
)

__all__ += [
    "ActionSuggestion",
    "DecompositionError",
    "DecompositionFinding",
    "DecompositionPolicy",
    "DecompositionResult",
    "GeneratedAction",
    "RollingWaveAdapter",
    "decompose_plan_option",
]

from .capacity import (
    CapacityError,
    CapacityFinding,
    CapacityView,
    PortfolioCapacityReport,
    RecurringWorkload,
    check_portfolio_capacity,
)

__all__ += [
    "CapacityError",
    "CapacityFinding",
    "CapacityView",
    "PortfolioCapacityReport",
    "RecurringWorkload",
    "check_portfolio_capacity",
]

from .explanations import (
    ComparisonDimension,
    ContradictionSummary,
    CounterfactualResult,
    ExplanationError,
    ItemExplanation,
    OmissionSummary,
    PlanExplanation,
    PlanOptionComparison,
    ProvenanceEntry,
    compare_plan_options,
    explain_plan_option,
    recompute_capacity_counterfactual,
)

__all__ += [
    "ComparisonDimension",
    "ContradictionSummary",
    "CounterfactualResult",
    "ExplanationError",
    "ItemExplanation",
    "OmissionSummary",
    "PlanExplanation",
    "PlanOptionComparison",
    "ProvenanceEntry",
    "compare_plan_options",
    "explain_plan_option",
    "recompute_capacity_counterfactual",
]

from .proposals import (
    ConflictPlanEdit,
    CopilotProposalError,
    CopilotProposalRequest,
    CopilotProposalResult,
    create_copilot_plan_proposal,
)

__all__ += [
    "ConflictPlanEdit",
    "CopilotProposalError",
    "CopilotProposalRequest",
    "CopilotProposalResult",
    "create_copilot_plan_proposal",
]

from .replanning import (
    ReplanningComparison,
    ReplanningError,
    ReplanningProposalRequest,
    ReplanningProposalResult,
    ReplanningReview,
    ReplanningTrigger,
    ReviewEvidence,
    build_replanning_review,
    create_replanning_proposal,
    scan_replanning_triggers,
    suppress_replanning_suggestion,
)

__all__ += [
    "ReplanningComparison",
    "ReplanningError",
    "ReplanningProposalRequest",
    "ReplanningProposalResult",
    "ReplanningReview",
    "ReplanningTrigger",
    "ReviewEvidence",
    "build_replanning_review",
    "create_replanning_proposal",
    "scan_replanning_triggers",
    "suppress_replanning_suggestion",
]
