"""Deterministic descriptive analysis for personal experiments."""

from __future__ import annotations

import math
import secrets
import statistics
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from .artifact import ExperimentArtifactService, utc_now
from .contracts import AnalysisRecord, ConclusionKind, ExperimentArtifact, ExperimentError, MeasureDefinition, Observation


def _numeric(observations: Iterable[Observation]) -> tuple[tuple[str, float], ...]:
    result: list[tuple[str, float]] = []
    for item in observations:
        if item.state != "measured" or isinstance(item.value, str) or item.value is None:
            continue
        value = 1.0 if item.value is True else 0.0 if item.value is False else float(item.value)
        if math.isfinite(value):
            result.append((item.observation_id, value))
    return tuple(result)


def _summary(values: tuple[tuple[str, float], ...]) -> dict[str, object]:
    numbers = [value for _, value in values]
    return {
        "count": len(numbers),
        "mean": statistics.fmean(numbers) if numbers else None,
        "median": statistics.median(numbers) if numbers else None,
        "min": min(numbers) if numbers else None,
        "max": max(numbers) if numbers else None,
        "observation_ids": [item_id for item_id, _ in values],
    }


def analyze_experiment(artifact: ExperimentArtifact, *, now: datetime | None = None) -> AnalysisRecord:
    moment = utc_now(now)
    metadata = artifact.metadata
    observations = metadata.observations
    summaries: list[dict[str, object]] = []
    used_ids: set[str] = set()
    limitations = [
        "This is descriptive evidence from a personal experiment and does not establish causation.",
        "Uncontrolled events and measurement error may explain observed differences.",
    ]
    total = len(observations)
    missing = sum(item.state != "measured" for item in observations)
    summaries.append({
        "label": "Data completeness",
        "text": f"{total - missing} measured of {total} recorded observations; {missing} explicit missing or skipped.",
        "observation_count": total,
        "missing_count": missing,
        "missing_rate": missing / total if total else None,
    })
    phases_by_kind = {phase.phase_id: phase.kind for phase in metadata.protocol.phases}
    for measure in metadata.protocol.outcome_measures:
        measure_observations = tuple(item for item in observations if item.measure_id == measure.measure_id)
        if measure.kind == "qualitative":
            measured = tuple(item for item in measure_observations if item.state == "measured")
            used_ids.update(item.observation_id for item in measured)
            summaries.append({
                "measure_id": measure.measure_id,
                "label": measure.display_name,
                "kind": "qualitative-counts",
                "text": f"{len(measured)} qualitative observations are available for inspection; no themes were invented deterministically.",
                "measured_count": len(measured),
                "observation_ids": [item.observation_id for item in measured],
            })
            continue
        phase_values: dict[str, tuple[tuple[str, float], ...]] = {}
        for phase_id in {item.phase_id for item in measure_observations}:
            values = _numeric(item for item in measure_observations if item.phase_id == phase_id)
            phase_values[phase_id] = values
            used_ids.update(item_id for item_id, _ in values)
        phase_summaries = {phase_id: _summary(values) for phase_id, values in sorted(phase_values.items())}
        baseline_values = tuple(
            pair for phase_id, values in phase_values.items() if phases_by_kind.get(phase_id) == "baseline" for pair in values
        )
        intervention_values = tuple(
            pair for phase_id, values in phase_values.items() if phases_by_kind.get(phase_id) == "intervention" for pair in values
        )
        baseline = _summary(baseline_values)
        intervention = _summary(intervention_values)
        change = None
        if baseline["mean"] is not None and intervention["mean"] is not None:
            change = float(intervention["mean"]) - float(baseline["mean"])
        summaries.append({
            "measure_id": measure.measure_id,
            "label": measure.display_name,
            "kind": "phase-comparison",
            "text": (
                f"Baseline mean {baseline['mean']}; intervention mean {intervention['mean']}; change {change}."
                if change is not None else "Not enough measured baseline and intervention values for a comparison."
            ),
            "phases": phase_summaries,
            "baseline": baseline,
            "intervention": intervention,
            "change_from_baseline": change,
        })
    adherence = [item for item in metadata.protocol.outcome_measures if item.role == "adherence"]
    if adherence:
        adherence_ids = {item.measure_id for item in adherence}
        adherence_observations = tuple(item for item in observations if item.measure_id in adherence_ids)
        measured_values = _numeric(adherence_observations)
        used_ids.update(item_id for item_id, _ in measured_values)
        rate = statistics.fmean(value for _, value in measured_values) if measured_values else None
        summaries.append({"label": "Adherence", "text": f"Observed adherence rate: {rate}." if rate is not None else "No measured adherence data.", "rate": rate})
    measured_count = sum(item.state == "measured" for item in observations)
    primary_ids = {item.measure_id for item in metadata.protocol.outcome_measures if item.role == "primary"}
    baseline_primary = sum(item.state == "measured" and item.measure_id in primary_ids and phases_by_kind.get(item.phase_id) == "baseline" for item in observations)
    intervention_primary = sum(item.state == "measured" and item.measure_id in primary_ids and phases_by_kind.get(item.phase_id) == "intervention" for item in observations)
    if metadata.safety.level in {"blocked", "emergency"}:
        status = "stopped-for-safety"
    elif measured_count == 0 or baseline_primary < 2 or intervention_primary < 2:
        status = "insufficient-evidence"
        limitations.append("At least two measured primary observations in both baseline and intervention are required for a phase comparison.")
    elif any("confound" in item.casefold() for observation in observations for item in observation.context):
        status = "confounded"
        limitations.append("One or more observations explicitly record a possible confounder.")
    else:
        status = "ready"
    return AnalysisRecord(
        f"analysis-{secrets.token_hex(8)}", moment.isoformat(), status, tuple(summaries), tuple(sorted(used_ids)),
        ("Observation timestamps and phase assignments are treated as recorded.",),
        "Only state=measured values are included. not-measured, not-applicable, skipped, and unavailable are reported but never converted to zero.",
        tuple(limitations), "descriptive",
    )


def save_analysis(
    service: ExperimentArtifactService,
    artifact: ExperimentArtifact,
    *,
    expected_hash: str,
    now: datetime | None = None,
) -> ExperimentArtifact:
    analysis = analyze_experiment(artifact, now=now)
    moment = utc_now(now)
    metadata = replace(artifact.metadata, analyses=(*artifact.metadata.analyses, analysis), updated_at=moment.isoformat())
    return service.save(artifact, metadata, expected_hash=expected_hash)


def record_conclusion(
    service: ExperimentArtifactService,
    artifact: ExperimentArtifact,
    *,
    conclusion: ConclusionKind,
    notes: str,
    follow_up_decisions: tuple[str, ...],
    expected_hash: str,
    now: datetime | None = None,
) -> ExperimentArtifact:
    if not artifact.metadata.analyses and conclusion not in {"abandoned-without-analysis", "stopped-for-safety"}:
        raise ExperimentError("analysis_required", "Record an analysis before this conclusion.")
    moment = utc_now(now)
    metadata = replace(
        artifact.metadata,
        conclusion=conclusion,
        conclusion_notes=notes.strip(),
        follow_up_decisions=follow_up_decisions,
        updated_at=moment.isoformat(),
    )
    return service.save(artifact, metadata, expected_hash=expected_hash)
