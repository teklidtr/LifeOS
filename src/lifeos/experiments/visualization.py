"""Chart-ready derived experiment views that preserve raw values and uncertainty."""

from __future__ import annotations

from .contracts import ExperimentArtifact
from .scheduling import build_collection_windows
from datetime import datetime


def build_visual_model(artifact: ExperimentArtifact, *, now: datetime) -> dict[str, object]:
    phases = [phase.to_dict() for phase in artifact.metadata.protocol.phases]
    observations = [
        {
            "observation_id": item.observation_id,
            "measure_id": item.measure_id,
            "phase_id": item.phase_id,
            "observed_at": item.observed_at,
            "state": item.state,
            "value": item.value,
            "note": item.note,
        }
        for item in artifact.metadata.observations
    ]
    windows = [item.to_dict() for item in build_collection_windows(artifact.metadata, now=now)]
    return {
        "experiment_id": artifact.metadata.experiment_id,
        "phase_timeline": phases,
        "observations": observations,
        "observation_calendar": windows,
        "amendment_markers": [item.to_dict() for item in artifact.metadata.amendments],
        "missing_indicators": [item["observation_id"] for item in observations if item["state"] != "measured"],
        "render_fallback": "Open the canonical experiment note to inspect raw phases, observations, amendments, and analysis.",
    }
