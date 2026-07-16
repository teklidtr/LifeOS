"""Personal experiment public API."""

from .analysis import analyze_experiment, record_conclusion, save_analysis
from .artifact import ExperimentArtifactService, parse_experiment, protocol_hash
from .assistance import (
    AssistanceRequest,
    AssistanceResult,
    DeterministicExperimentAssistance,
    assist_design,
)
from .contracts import (
    EXPERIMENT_SCHEMA_VERSION,
    AnalysisRecord,
    ConclusionKind,
    ExperimentArtifact,
    ExperimentError,
    ExperimentMetadata,
    ExperimentPhase,
    ExperimentProtocol,
    ExperimentState,
    LifecycleEvent,
    MeasureDefinition,
    Observation,
    ProtocolAmendment,
    SafetyClassification,
    SourceReference,
    protocol_from_dict,
    validate_transition,
)
from .design import DesignWarning, evaluate_design
from .history import (
    ExperimentIndexEntry,
    ExperimentIndexReport,
    compare_experiments,
    load_experiment_index,
    rebuild_experiment_index,
)
from .migration import (
    ExperimentMigrationCandidate,
    ExperimentMigrationPreview,
    ExperimentMigrationResult,
    LegacyExperimentSource,
    apply_experiment_migration,
    preview_experiment_migration,
)
from .observations import create_observation
from .privacy import (
    PROTECTED_ROOTS,
    ExperimentContextItem,
    ExperimentContextOmission,
    ExperimentContextPreview,
    preview_experiment_context,
)
from .proposals import (
    ExperimentProposalPreview,
    ExperimentProposalRequest,
    ExperimentProposalService,
)
from .recovery import ExperimentRecoveryReport, audit_experiment_recovery
from .safety import ImmediateSafetyMessage, classify_safety, immediate_message
from .scheduling import CollectionWindow, build_collection_windows, due_windows
from .visualization import build_visual_model

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "PROTECTED_ROOTS",
    "AnalysisRecord",
    "AssistanceRequest",
    "AssistanceResult",
    "CollectionWindow",
    "ConclusionKind",
    "DesignWarning",
    "DeterministicExperimentAssistance",
    "ExperimentArtifact",
    "ExperimentArtifactService",
    "ExperimentContextItem",
    "ExperimentContextOmission",
    "ExperimentContextPreview",
    "ExperimentError",
    "ExperimentIndexEntry",
    "ExperimentIndexReport",
    "ExperimentMetadata",
    "ExperimentMigrationCandidate",
    "ExperimentMigrationPreview",
    "ExperimentMigrationResult",
    "ExperimentPhase",
    "ExperimentProposalPreview",
    "ExperimentProposalRequest",
    "ExperimentProposalService",
    "ExperimentProtocol",
    "ExperimentRecoveryReport",
    "ExperimentState",
    "ImmediateSafetyMessage",
    "LegacyExperimentSource",
    "LifecycleEvent",
    "MeasureDefinition",
    "Observation",
    "ProtocolAmendment",
    "SafetyClassification",
    "SourceReference",
    "analyze_experiment",
    "apply_experiment_migration",
    "assist_design",
    "audit_experiment_recovery",
    "build_collection_windows",
    "build_visual_model",
    "classify_safety",
    "compare_experiments",
    "create_observation",
    "due_windows",
    "evaluate_design",
    "immediate_message",
    "load_experiment_index",
    "parse_experiment",
    "preview_experiment_context",
    "preview_experiment_migration",
    "protocol_from_dict",
    "protocol_hash",
    "rebuild_experiment_index",
    "record_conclusion",
    "save_analysis",
    "validate_transition",
]
