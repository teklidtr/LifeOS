"""Observation creation and validation helpers."""

from __future__ import annotations

import secrets
from datetime import datetime

from .contracts import ExperimentError, ExperimentMetadata, Observation, ObservationState, SourceReference


def create_observation(
    metadata: ExperimentMetadata,
    *,
    measure_id: str,
    phase_id: str,
    observed_at: datetime,
    state: ObservationState,
    value: float | bool | str | None = None,
    note: str = "",
    source_refs: tuple[SourceReference, ...] = (),
    context: tuple[str, ...] = (),
    observation_id: str | None = None,
) -> Observation:
    if observed_at.tzinfo is None:
        raise ExperimentError("invalid_timestamp", "Observation timestamps must include a timezone.")
    measure = next((item for item in metadata.protocol.outcome_measures if item.measure_id == measure_id), None)
    if measure is None:
        raise ExperimentError("unknown_measure", "Observation measure is not defined by the protocol.")
    if phase_id not in {item.phase_id for item in metadata.protocol.phases}:
        raise ExperimentError("unknown_phase", "Observation phase is not defined by the protocol.")
    if state == "measured":
        if measure.kind == "qualitative" and not isinstance(value, str):
            raise ExperimentError("invalid_observation", "Qualitative measures require a text value.")
        if measure.kind != "qualitative" and not isinstance(value, (int, float, bool)):
            raise ExperimentError("invalid_observation", "Quantitative measures require a number or completion value.")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if measure.valid_min is not None and numeric < measure.valid_min:
                raise ExperimentError("out_of_range", "Observation is below the measure's valid range.")
            if measure.valid_max is not None and numeric > measure.valid_max:
                raise ExperimentError("out_of_range", "Observation is above the measure's valid range.")
    return Observation(
        observation_id or f"obs-{secrets.token_hex(8)}",
        measure_id,
        observed_at.isoformat(),
        phase_id,
        state,
        value,
        note.strip(),
        source_refs,
        context,
    )
