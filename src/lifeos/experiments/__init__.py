"""Personal experiment public API."""

from .artifact import ExperimentArtifactService, parse_experiment, protocol_hash
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
    validate_transition,
)

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "AnalysisRecord",
    "ConclusionKind",
    "ExperimentArtifact",
    "ExperimentArtifactService",
    "ExperimentError",
    "ExperimentMetadata",
    "ExperimentPhase",
    "ExperimentProtocol",
    "ExperimentState",
    "LifecycleEvent",
    "MeasureDefinition",
    "Observation",
    "ProtocolAmendment",
    "SafetyClassification",
    "SourceReference",
    "parse_experiment",
    "protocol_hash",
    "validate_transition",
]
from .assistance import AssistanceRequest, AssistanceResult, DeterministicExperimentAssistance, assist_design
from .design import DesignWarning, evaluate_design
from .safety import ImmediateSafetyMessage, classify_safety, immediate_message
from .scheduling import CollectionWindow, build_collection_windows, due_windows

__all__ += [
    "AssistanceRequest", "AssistanceResult", "CollectionWindow", "DesignWarning",
    "DeterministicExperimentAssistance", "ImmediateSafetyMessage", "assist_design",
    "build_collection_windows", "classify_safety", "due_windows", "evaluate_design", "immediate_message",
]
from .analysis import analyze_experiment, record_conclusion, save_analysis
from .history import ExperimentIndexEntry, ExperimentIndexReport, compare_experiments, load_experiment_index, rebuild_experiment_index
from .observations import create_observation
from .visualization import build_visual_model

__all__ += [
    "ExperimentIndexEntry", "ExperimentIndexReport", "analyze_experiment", "build_visual_model",
    "compare_experiments", "create_observation", "load_experiment_index", "rebuild_experiment_index",
    "record_conclusion", "save_analysis",
]
