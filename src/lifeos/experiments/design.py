"""Inspectable experiment-design guidance without opaque scoring."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal, Sequence

from .contracts import ExperimentArtifact, ExperimentProtocol


@dataclass(frozen=True, slots=True)
class DesignWarning:
    code: str
    severity: Literal["recommendation", "warning", "blocking"]
    title: str
    explanation: str
    recommendation: str
    evidence: tuple[str, ...] = ()
    acknowledgeable: bool = True

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "evidence": list(self.evidence)}


def _phase_days(protocol: ExperimentProtocol) -> int:
    total = 0
    for phase in protocol.phases:
        try:
            total += (date.fromisoformat(phase.end_date) - date.fromisoformat(phase.start_date)).days + 1
        except ValueError:
            continue
    return total


def evaluate_design(
    protocol: ExperimentProtocol,
    *,
    active_experiments: Sequence[ExperimentArtifact] = (),
    current_experiment_id: str | None = None,
) -> tuple[DesignWarning, ...]:
    warnings: list[DesignWarning] = []
    intervention_parts = tuple(part.strip() for part in protocol.intervention.replace(" and ", ";").split(";") if part.strip())
    if len(intervention_parts) > 1:
        warnings.append(DesignWarning(
            "multiple-interventions", "warning", "Several changes are bundled together",
            "Changing several things at once makes it difficult to know which change coincided with the outcome.",
            "Reduce the protocol to one main change or explicitly treat it as a bundled intervention.", intervention_parts,
        ))
    if not protocol.outcome_measures:
        warnings.append(DesignWarning(
            "no-outcomes", "warning", "No outcome is observable",
            "The protocol does not define any quantitative or qualitative outcome measure.",
            "Add at least one primary measure with a collection cadence.",
        ))
    vague = tuple(item.display_name for item in protocol.outcome_measures if item.kind == "qualitative" and len(item.display_name.split()) < 2)
    if vague:
        warnings.append(DesignWarning(
            "vague-outcomes", "recommendation", "Some outcomes may be too vague",
            "Broad labels can drift in meaning during collection.",
            "Add anchors or a short prompt describing what each rating or note should capture.", vague,
        ))
    has_baseline = bool(protocol.comparison.strip()) or any(phase.kind == "baseline" for phase in protocol.phases)
    if not has_baseline:
        warnings.append(DesignWarning(
            "no-baseline", "warning", "No comparison or baseline is defined",
            "Without a comparison period, change from ordinary variation is harder to inspect.",
            "Add a baseline, comparison condition, or explain why neither is practical.",
        ))
    total_days = _phase_days(protocol)
    if total_days and total_days < 7:
        warnings.append(DesignWarning(
            "short-duration", "recommendation", "The planned duration is probably short",
            f"The protocol spans {total_days} days, which may capture only a few observations.",
            "Extend the protocol or define in advance that the result may remain inconclusive.", (str(total_days),),
        ))
    sparse = tuple(item.display_name for item in protocol.outcome_measures if item.cadence.casefold() in {"monthly", "once", "end-only"})
    if sparse:
        warnings.append(DesignWarning(
            "sparse-measurement", "warning", "Measurements may be too infrequent",
            "Sparse collection can hide missingness and short-lived changes.",
            "Increase cadence or extend the experiment duration.", sparse,
        ))
    if not protocol.success_criteria or not protocol.inconclusive_criteria:
        warnings.append(DesignWarning(
            "criteria-incomplete", "warning", "Decision criteria are incomplete",
            "Success and inconclusive rules should be written before results are visible.",
            "Add precommitted success and inconclusive criteria.",
        ))
    retrospective = tuple(item.display_name for item in protocol.outcome_measures if "retrospective" in item.source.casefold() or "memory" in item.source.casefold())
    if retrospective and len(retrospective) == len(protocol.outcome_measures):
        warnings.append(DesignWarning(
            "retrospective-only", "warning", "The protocol relies entirely on retrospective memory",
            "Memory-based summaries can blur timing and missing observations.",
            "Add a brief contemporaneous observation or link to an existing daily artifact.", retrospective,
        ))
    if not any(item.role == "adherence" for item in protocol.outcome_measures):
        warnings.append(DesignWarning(
            "adherence-unmeasured", "recommendation", "Adherence cannot be separated from outcome",
            "A null result may mean the intervention had no effect or was not followed.",
            "Add a completion or adherence measure.",
        ))
    current_measures = {item.measure_id for item in protocol.outcome_measures}
    for active in active_experiments:
        if active.metadata.experiment_id == current_experiment_id:
            continue
        same_intervention = active.metadata.protocol.intervention.casefold().strip() == protocol.intervention.casefold().strip()
        overlap = current_measures & {item.measure_id for item in active.metadata.protocol.outcome_measures}
        if same_intervention:
            warnings.append(DesignWarning(
                "duplicate-active-experiment", "warning", "A similar experiment is already active",
                f"{active.metadata.title} tests the same intervention.",
                "Continue the existing experiment, clone it later, or explain why both are needed.", (active.path,),
            ))
        elif overlap:
            warnings.append(DesignWarning(
                "overlapping-experiment", "warning", "Another active experiment may confound these outcomes",
                f"{active.metadata.title} observes overlapping measures: {', '.join(sorted(overlap))}.",
                "Avoid overlap, stagger phases, or record the other experiment as a confounder.", (active.path, *sorted(overlap)),
            ))
    return tuple(warnings)
