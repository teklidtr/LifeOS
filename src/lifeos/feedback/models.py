"""Typed adaptive-feedback contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

AdaptiveMode = Literal["off", "shadow", "active"]
Confidence = Literal["insufficient", "low", "moderate", "high"]
EvidenceOutcome = Literal[
    "started", "done", "partial", "skipped", "deferred", "cancelled", "unaccounted"
]


@dataclass(frozen=True, slots=True)
class FeedbackDiagnostic:
    code: str
    message: str
    source_path: str | None = None
    event_id: str | None = None
    severity: Literal["warning", "error"] = "error"


@dataclass(frozen=True, slots=True)
class FeedbackObservation:
    schema_version: int
    observation_id: str
    event_id: str
    source_path: str
    source_hash: str
    source_index: int
    day: date
    plan_id: str
    goal_id: str
    task_id: str
    task_title: str
    task_shape: str
    mode: str
    task_energy: str | None
    task_motivation: str | None
    blocked: bool | None
    outcome: EvidenceOutcome
    completion_fraction: float | None
    planned_minutes: int | None
    actual_minutes: int | None
    energy_before: str | None
    energy_after: str | None
    motivation_before: str | None
    started_at: str | None
    ended_at: str | None
    reason: str | None
    correction_lineage: tuple[str, ...]
    excluded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceDataset:
    schema_version: int
    as_of: date
    source_fingerprint: str
    observations: tuple[FeedbackObservation, ...]
    diagnostics: tuple[FeedbackDiagnostic, ...]
    excluded_event_ids: tuple[str, ...]
    corrected_event_count: int
    retracted_event_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceDatasetStatus:
    status: Literal["empty", "ready", "diagnostic", "unsupported", "unavailable"]
    schema_version: int
    observation_count: int
    diagnostic_count: int
    excluded_count: int
    corrected_count: int
    retracted_count: int
    source_fingerprint: str
    cache_path: str
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DurationForecast:
    schema_version: int
    task_id: str
    declared_minutes: int
    calibrated_minutes: int
    evidence_level: Literal["task", "task_shape", "plan", "mode", "global", "none"]
    evidence_key: str
    sample_count: int
    excluded_outliers: int
    median_ratio: float | None
    spread: float | None
    freshest_day: date | None
    confidence: Confidence
    direction: Literal["underestimated", "overestimated", "aligned", "unknown"]
    evidence_event_ids: tuple[str, ...]
    ignored_reasons: tuple[str, ...]
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapacityDimension:
    name: Literal["energy", "motivation", "mode", "duration_band", "time_window", "blocker"]
    status: Literal["used", "disabled", "missing", "insufficient", "contradictory"]
    sample_count: int
    missing_count: int
    success_rate: float | None
    baseline_rate: float | None
    adjustment: float
    direction: Literal["better_fit", "worse_fit", "neutral", "unknown"]
    confidence: Confidence
    evidence_event_ids: tuple[str, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class CapacityFitSummary:
    schema_version: int
    task_id: str
    total_adjustment: float
    confidence: Confidence
    dimensions: tuple[CapacityDimension, ...]
    ignored_dimensions: tuple[str, ...]
    caveat: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AvoidanceDiagnosis:
    schema_version: int
    diagnosis_id: str
    evidence_fingerprint: str
    task_id: str
    plan_id: str
    kind: Literal[
        "underspecified",
        "oversized",
        "blocked",
        "estimate_error",
        "capacity_mismatch",
        "motivation_mismatch",
        "unaccounted",
        "stalled",
    ]
    title: str
    hypothesis: str
    confidence: Confidence
    evidence_event_ids: tuple[str, ...]
    evidence_dates: tuple[date, ...]
    competing_explanations: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    suggested_actions: tuple[str, ...]
    dismissed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AdaptiveAdjustment:
    task_id: str
    declared_minutes: int
    effective_minutes: int
    duration_forecast: DurationForecast
    capacity_fit: CapacityFitSummary
    diagnosis_ids: tuple[str, ...]
    capped: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveMenuDelta:
    task_id: str
    baseline_selected: bool
    adaptive_selected: bool
    declared_minutes: int
    effective_minutes: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdaptivePlanResult:
    schema_version: int
    policy_version: int
    mode: AdaptiveMode
    baseline: dict[str, Any]
    adaptive: dict[str, Any]
    returned: dict[str, Any]
    adjustments: tuple[AdaptiveAdjustment, ...]
    deltas: tuple[AdaptiveMenuDelta, ...]
    feedback_status: Literal["unavailable", "insufficient", "available", "diagnostic"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlannerCounterfactual:
    code: str
    label: str
    value: str | int | None


@dataclass(frozen=True, slots=True)
class PlannerExplanation:
    schema_version: int
    policy_version: int
    task_id: str
    selected_in_baseline: bool
    selected_in_adaptive: bool
    baseline_rank: int | None
    adaptive_rank: int | None
    declared_minutes: int
    calibrated_minutes: int
    effective_minutes: int
    confidence: Confidence
    reason_codes: tuple[str, ...]
    ignored_signals: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    concise: str
    expanded: tuple[str, ...]
    counterfactuals: tuple[PlannerCounterfactual, ...]
    privacy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
