"""Canonical contracts for safety-aware personal experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence

EXPERIMENT_SCHEMA_VERSION = 1
ExperimentState = Literal[
    "idea",
    "drafting",
    "baseline",
    "scheduled",
    "active",
    "paused",
    "completed",
    "abandoned",
    "analyzed",
    "archived",
]
MeasureKind = Literal["count", "duration", "rating", "percentage", "continuous", "completion", "qualitative"]
MeasureRole = Literal["primary", "secondary", "adherence", "contextual"]
ObservationState = Literal["measured", "not-measured", "not-applicable", "skipped", "unavailable"]
SafetyLevel = Literal["ordinary", "caution", "informational-only", "blocked", "emergency"]
ConclusionKind = Literal[
    "supports-hypothesis",
    "does-not-support-hypothesis",
    "mixed",
    "inconclusive",
    "protocol-failure",
    "insufficient-adherence",
    "insufficient-duration",
    "too-much-missing-data",
    "confounded",
    "stopped-for-safety",
    "abandoned-without-analysis",
]

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "idea": frozenset({"drafting", "abandoned", "archived"}),
    "drafting": frozenset({"idea", "baseline", "scheduled", "abandoned", "archived"}),
    "baseline": frozenset({"scheduled", "active", "paused", "completed", "abandoned"}),
    "scheduled": frozenset({"baseline", "active", "paused", "abandoned"}),
    "active": frozenset({"paused", "completed", "abandoned"}),
    "paused": frozenset({"baseline", "scheduled", "active", "completed", "abandoned"}),
    "completed": frozenset({"analyzed", "archived"}),
    "abandoned": frozenset({"analyzed", "archived"}),
    "analyzed": frozenset({"archived"}),
    "archived": frozenset(),
}


class ExperimentError(ValueError):
    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


def _nonblank(value: str, field_name: str) -> str:
    result = value.strip()
    if not result:
        raise ExperimentError("invalid_field", f"{field_name} must not be blank.", {"field": field_name})
    return result


def validate_transition(current: ExperimentState, target: ExperimentState) -> None:
    if target == current:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ExperimentError(
            "invalid_transition",
            f"Experiment cannot transition from {current} to {target}.",
            {"current": current, "target": target, "allowed": sorted(_ALLOWED_TRANSITIONS[current])},
        )


@dataclass(frozen=True, slots=True)
class SourceReference:
    path: str
    relation: str = "source"
    content_hash: str | None = None

    def __post_init__(self) -> None:
        _nonblank(self.path, "source path")
        _nonblank(self.relation, "source relation")
        if self.content_hash is not None and not self.content_hash.startswith("sha256:"):
            raise ExperimentError("invalid_source", "Source hash must use the sha256: prefix.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MeasureDefinition:
    measure_id: str
    display_name: str
    kind: MeasureKind
    role: MeasureRole
    cadence: str
    unit: str | None = None
    source: str = "manual"
    direction: Literal["increase", "decrease", "neutral", "unknown"] = "unknown"
    valid_min: float | None = None
    valid_max: float | None = None
    missing_behavior: Literal["exclude", "report", "carry-none"] = "report"
    aggregation: Literal["mean", "median", "sum", "rate", "latest", "none"] = "mean"

    def __post_init__(self) -> None:
        _nonblank(self.measure_id, "measure_id")
        _nonblank(self.display_name, "display_name")
        _nonblank(self.cadence, "cadence")
        _nonblank(self.source, "source")
        if self.valid_min is not None and self.valid_max is not None and self.valid_min > self.valid_max:
            raise ExperimentError("invalid_measure", "Measure valid_min cannot exceed valid_max.")
        if self.kind == "qualitative" and self.aggregation != "none":
            raise ExperimentError("invalid_measure", "Qualitative measures must use aggregation=none.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExperimentPhase:
    phase_id: str
    name: str
    kind: Literal["baseline", "intervention", "washout", "follow-up"]
    start_date: str
    end_date: str
    intervention: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.phase_id, "phase_id")
        _nonblank(self.name, "phase name")
        if self.end_date < self.start_date:
            raise ExperimentError("invalid_phase", "Experiment phase end date precedes its start date.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    measure_id: str
    observed_at: str
    phase_id: str
    state: ObservationState
    value: float | bool | str | None = None
    note: str = ""
    source_refs: tuple[SourceReference, ...] = ()
    context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _nonblank(self.observation_id, "observation_id")
        _nonblank(self.measure_id, "measure_id")
        _nonblank(self.observed_at, "observed_at")
        _nonblank(self.phase_id, "phase_id")
        if self.state == "measured" and self.value is None:
            raise ExperimentError("invalid_observation", "Measured observations require a value.")
        if self.state != "measured" and self.value is not None:
            raise ExperimentError(
                "invalid_observation",
                "Only measured observations may carry a value; missing and skipped states remain explicit.",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "context": list(self.context),
        }


@dataclass(frozen=True, slots=True)
class ProtocolAmendment:
    amendment_id: str
    created_at: str
    reason: str
    changes: tuple[str, ...]
    prior_protocol_hash: str

    def __post_init__(self) -> None:
        _nonblank(self.amendment_id, "amendment_id")
        _nonblank(self.reason, "amendment reason")
        if not self.changes:
            raise ExperimentError("invalid_amendment", "An amendment must describe at least one change.")
        if not self.prior_protocol_hash.startswith("sha256:"):
            raise ExperimentError("invalid_amendment", "Amendment prior protocol hash is invalid.")

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "changes": list(self.changes)}


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    from_state: ExperimentState | None
    to_state: ExperimentState
    occurred_at: str
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SafetyClassification:
    level: SafetyLevel = "ordinary"
    codes: tuple[str, ...] = ()
    explanation: str = "No blocking safety issue detected by deterministic policy."
    professional_guidance_recommended: bool = False

    @property
    def allows_activation(self) -> bool:
        return self.level not in {"informational-only", "blocked", "emergency"}

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "codes": list(self.codes), "allows_activation": self.allows_activation}


@dataclass(frozen=True, slots=True)
class ExperimentProtocol:
    question: str
    hypothesis: str
    rationale: str
    intervention: str
    constants: tuple[str, ...]
    comparison: str
    baseline_requirements: str
    outcome_measures: tuple[MeasureDefinition, ...]
    phases: tuple[ExperimentPhase, ...]
    adherence_expectation: str
    confounders: tuple[str, ...]
    risks: tuple[str, ...]
    stop_rules: tuple[str, ...]
    success_criteria: tuple[str, ...]
    failure_criteria: tuple[str, ...]
    inconclusive_criteria: tuple[str, ...]
    schedule: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonblank(self.question, "question")
        _nonblank(self.hypothesis, "hypothesis")
        _nonblank(self.intervention, "intervention")
        measure_ids = [item.measure_id for item in self.outcome_measures]
        if len(measure_ids) != len(set(measure_ids)):
            raise ExperimentError("duplicate_measure", "Experiment measure identities must be unique.")
        phase_ids = [item.phase_id for item in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ExperimentError("duplicate_phase", "Experiment phase identities must be unique.")

    def to_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "hypothesis": self.hypothesis,
            "rationale": self.rationale,
            "intervention": self.intervention,
            "constants": list(self.constants),
            "comparison": self.comparison,
            "baseline_requirements": self.baseline_requirements,
            "outcome_measures": [item.to_dict() for item in self.outcome_measures],
            "phases": [item.to_dict() for item in self.phases],
            "adherence_expectation": self.adherence_expectation,
            "confounders": list(self.confounders),
            "risks": list(self.risks),
            "stop_rules": list(self.stop_rules),
            "success_criteria": list(self.success_criteria),
            "failure_criteria": list(self.failure_criteria),
            "inconclusive_criteria": list(self.inconclusive_criteria),
            "schedule": dict(self.schedule),
        }


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    analysis_id: str
    created_at: str
    status: Literal["ready", "insufficient-evidence", "confounded", "stopped-for-safety"]
    summaries: tuple[dict[str, object], ...]
    observation_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    missing_data_treatment: str
    limitations: tuple[str, ...]
    evidence_kind: Literal["descriptive", "inferential"] = "descriptive"

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "summaries": [dict(item) for item in self.summaries],
            "observation_ids": list(self.observation_ids),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ExperimentMetadata:
    experiment_id: str
    title: str
    description: str
    state: ExperimentState
    category: str
    created_at: str
    updated_at: str
    protocol: ExperimentProtocol
    safety: SafetyClassification = SafetyClassification()
    origins: tuple[SourceReference, ...] = ()
    linked_habits: tuple[str, ...] = ()
    linked_metrics: tuple[str, ...] = ()
    linked_tasks: tuple[str, ...] = ()
    linked_diary: tuple[str, ...] = ()
    linked_checkins: tuple[str, ...] = ()
    linked_reviews: tuple[str, ...] = ()
    source_refs: tuple[SourceReference, ...] = ()
    observations: tuple[Observation, ...] = ()
    amendments: tuple[ProtocolAmendment, ...] = ()
    lifecycle: tuple[LifecycleEvent, ...] = ()
    analyses: tuple[AnalysisRecord, ...] = ()
    conclusion: ConclusionKind | None = None
    conclusion_notes: str = ""
    follow_up_decisions: tuple[str, ...] = ()
    parent_experiment_id: str | None = None
    repeated_from_experiment_id: str | None = None
    schema_version: int = EXPERIMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXPERIMENT_SCHEMA_VERSION:
            raise ExperimentError("unsupported_schema", "Experiment schema version is unsupported.")
        if not self.experiment_id.startswith("exp-"):
            raise ExperimentError("invalid_experiment", "Experiment identity is invalid.")
        _nonblank(self.title, "title")
        observation_ids = [item.observation_id for item in self.observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise ExperimentError("duplicate_observation", "Observation identities must be unique.")
        known_measures = {item.measure_id for item in self.protocol.outcome_measures}
        unknown_measures = sorted({item.measure_id for item in self.observations} - known_measures)
        if unknown_measures:
            raise ExperimentError("unknown_measure", "Observations reference unknown measures.", {"measure_ids": unknown_measures})
        known_phases = {item.phase_id for item in self.protocol.phases}
        unknown_phases = sorted({item.phase_id for item in self.observations} - known_phases)
        if unknown_phases:
            raise ExperimentError("unknown_phase", "Observations reference unknown phases.", {"phase_ids": unknown_phases})

    def to_frontmatter(self) -> dict[str, object]:
        return {
            "type": "personal-experiment",
            "experiment_schema": self.schema_version,
            "experiment_id": self.experiment_id,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "protocol": self.protocol.to_dict(),
            "safety": self.safety.to_dict(),
            "origins": [item.to_dict() for item in self.origins],
            "linked_habits": list(self.linked_habits),
            "linked_metrics": list(self.linked_metrics),
            "linked_tasks": list(self.linked_tasks),
            "linked_diary": list(self.linked_diary),
            "linked_checkins": list(self.linked_checkins),
            "linked_reviews": list(self.linked_reviews),
            "source_refs": [item.to_dict() for item in self.source_refs],
            "observations": [item.to_dict() for item in self.observations],
            "amendments": [item.to_dict() for item in self.amendments],
            "lifecycle": [item.to_dict() for item in self.lifecycle],
            "analyses": [item.to_dict() for item in self.analyses],
            "conclusion": self.conclusion,
            "conclusion_notes": self.conclusion_notes,
            "follow_up_decisions": list(self.follow_up_decisions),
            "parent_experiment_id": self.parent_experiment_id,
            "repeated_from_experiment_id": self.repeated_from_experiment_id,
        }


@dataclass(frozen=True, slots=True)
class ExperimentArtifact:
    path: str
    content_hash: str
    metadata: ExperimentMetadata
    human_body: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "metadata": self.metadata.to_frontmatter(),
            "human_body": self.human_body,
        }


def _tuple_strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExperimentError("malformed_artifact", "Expected a list of strings.")
    return tuple(str(item) for item in value)


def source_from_dict(value: Mapping[str, Any]) -> SourceReference:
    return SourceReference(str(value["path"]), str(value.get("relation", "source")), str(value["content_hash"]) if value.get("content_hash") else None)


def measure_from_dict(value: Mapping[str, Any]) -> MeasureDefinition:
    return MeasureDefinition(
        measure_id=str(value["measure_id"]),
        display_name=str(value["display_name"]),
        kind=str(value["kind"]),  # type: ignore[arg-type]
        role=str(value["role"]),  # type: ignore[arg-type]
        cadence=str(value["cadence"]),
        unit=str(value["unit"]) if value.get("unit") is not None else None,
        source=str(value.get("source", "manual")),
        direction=str(value.get("direction", "unknown")),  # type: ignore[arg-type]
        valid_min=float(value["valid_min"]) if value.get("valid_min") is not None else None,
        valid_max=float(value["valid_max"]) if value.get("valid_max") is not None else None,
        missing_behavior=str(value.get("missing_behavior", "report")),  # type: ignore[arg-type]
        aggregation=str(value.get("aggregation", "mean")),  # type: ignore[arg-type]
    )


def phase_from_dict(value: Mapping[str, Any]) -> ExperimentPhase:
    return ExperimentPhase(
        str(value["phase_id"]), str(value["name"]), str(value["kind"]),  # type: ignore[arg-type]
        str(value["start_date"]), str(value["end_date"]), str(value.get("intervention", "")),
    )


def observation_from_dict(value: Mapping[str, Any]) -> Observation:
    return Observation(
        observation_id=str(value["observation_id"]),
        measure_id=str(value["measure_id"]),
        observed_at=str(value["observed_at"]),
        phase_id=str(value["phase_id"]),
        state=str(value["state"]),  # type: ignore[arg-type]
        value=value.get("value"),  # type: ignore[arg-type]
        note=str(value.get("note", "")),
        source_refs=tuple(source_from_dict(dict(item)) for item in value.get("source_refs", ())),
        context=_tuple_strings(value.get("context")),
    )


def protocol_from_dict(value: Mapping[str, Any]) -> ExperimentProtocol:
    return ExperimentProtocol(
        question=str(value["question"]),
        hypothesis=str(value["hypothesis"]),
        rationale=str(value.get("rationale", "")),
        intervention=str(value["intervention"]),
        constants=_tuple_strings(value.get("constants")),
        comparison=str(value.get("comparison", "")),
        baseline_requirements=str(value.get("baseline_requirements", "")),
        outcome_measures=tuple(measure_from_dict(dict(item)) for item in value.get("outcome_measures", ())),
        phases=tuple(phase_from_dict(dict(item)) for item in value.get("phases", ())),
        adherence_expectation=str(value.get("adherence_expectation", "")),
        confounders=_tuple_strings(value.get("confounders")),
        risks=_tuple_strings(value.get("risks")),
        stop_rules=_tuple_strings(value.get("stop_rules")),
        success_criteria=_tuple_strings(value.get("success_criteria")),
        failure_criteria=_tuple_strings(value.get("failure_criteria")),
        inconclusive_criteria=_tuple_strings(value.get("inconclusive_criteria")),
        schedule=dict(value.get("schedule", {})),
    )


def safety_from_dict(value: Mapping[str, Any] | None) -> SafetyClassification:
    data = dict(value or {})
    return SafetyClassification(
        str(data.get("level", "ordinary")),  # type: ignore[arg-type]
        _tuple_strings(data.get("codes")),
        str(data.get("explanation", "No blocking safety issue detected by deterministic policy.")),
        bool(data.get("professional_guidance_recommended", False)),
    )


def metadata_from_dict(value: Mapping[str, Any]) -> ExperimentMetadata:
    try:
        schema = int(value.get("experiment_schema", 0))
        if schema != EXPERIMENT_SCHEMA_VERSION:
            raise ExperimentError("unsupported_schema", "Experiment schema version is unsupported.", {"schema": schema})
        amendments = tuple(
            ProtocolAmendment(
                str(item["amendment_id"]), str(item["created_at"]), str(item["reason"]),
                _tuple_strings(item.get("changes")), str(item["prior_protocol_hash"]),
            )
            for item in (dict(raw) for raw in value.get("amendments", ()))
        )
        lifecycle = tuple(
            LifecycleEvent(
                str(item["event_id"]),
                str(item["from_state"]) if item.get("from_state") is not None else None,  # type: ignore[arg-type]
                str(item["to_state"]),  # type: ignore[arg-type]
                str(item["occurred_at"]), str(item.get("reason", "")),
            )
            for item in (dict(raw) for raw in value.get("lifecycle", ()))
        )
        analyses = tuple(
            AnalysisRecord(
                str(item["analysis_id"]), str(item["created_at"]), str(item["status"]),  # type: ignore[arg-type]
                tuple(dict(summary) for summary in item.get("summaries", ())),
                _tuple_strings(item.get("observation_ids")), _tuple_strings(item.get("assumptions")),
                str(item.get("missing_data_treatment", "Explicit missing states excluded from numeric summaries.")),
                _tuple_strings(item.get("limitations")), str(item.get("evidence_kind", "descriptive")),  # type: ignore[arg-type]
            )
            for item in (dict(raw) for raw in value.get("analyses", ()))
        )
        return ExperimentMetadata(
            experiment_id=str(value["experiment_id"]),
            title=str(value["title"]),
            description=str(value.get("description", "")),
            state=str(value["state"]),  # type: ignore[arg-type]
            category=str(value.get("category", "other")),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            protocol=protocol_from_dict(dict(value["protocol"])),
            safety=safety_from_dict(value.get("safety") if isinstance(value.get("safety"), Mapping) else None),
            origins=tuple(source_from_dict(dict(item)) for item in value.get("origins", ())),
            linked_habits=_tuple_strings(value.get("linked_habits")),
            linked_metrics=_tuple_strings(value.get("linked_metrics")),
            linked_tasks=_tuple_strings(value.get("linked_tasks")),
            linked_diary=_tuple_strings(value.get("linked_diary")),
            linked_checkins=_tuple_strings(value.get("linked_checkins")),
            linked_reviews=_tuple_strings(value.get("linked_reviews")),
            source_refs=tuple(source_from_dict(dict(item)) for item in value.get("source_refs", ())),
            observations=tuple(observation_from_dict(dict(item)) for item in value.get("observations", ())),
            amendments=amendments,
            lifecycle=lifecycle,
            analyses=analyses,
            conclusion=str(value["conclusion"]) if value.get("conclusion") else None,  # type: ignore[arg-type]
            conclusion_notes=str(value.get("conclusion_notes", "")),
            follow_up_decisions=_tuple_strings(value.get("follow_up_decisions")),
            parent_experiment_id=str(value["parent_experiment_id"]) if value.get("parent_experiment_id") else None,
            repeated_from_experiment_id=str(value["repeated_from_experiment_id"]) if value.get("repeated_from_experiment_id") else None,
            schema_version=schema,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ExperimentError):
            raise
        raise ExperimentError("malformed_artifact", "Experiment metadata is malformed.") from exc
