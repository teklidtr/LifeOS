"""Explicit links and experiment mappings for rich captures."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from lifeos.experiments.contracts import ExperimentArtifact, Observation, SourceReference
from lifeos.experiments.observations import create_observation

from .artifact import CaptureArtifactService, utc_now
from .contracts import ArtifactLink, CaptureArtifact, CaptureError


class CaptureLinkService:
    def __init__(self, captures: CaptureArtifactService) -> None:
        self.captures = captures

    def link(self, path: str, link: ArtifactLink, *, expected_hash: str, now: datetime | None = None) -> CaptureArtifact:
        artifact = self.captures.load(path)
        if artifact.content_hash != expected_hash:
            raise CaptureError("stale_capture", "Capture changed before linking.")
        key = (link.path, link.relation, link.artifact_type)
        if any((item.path, item.relation, item.artifact_type) == key for item in artifact.metadata.links):
            return artifact
        metadata = replace(artifact.metadata, links=(*artifact.metadata.links, link), updated_at=utc_now(now).isoformat())
        return self.captures.save(artifact, metadata, expected_hash=expected_hash)

    def unlink(self, path: str, target_path: str, *, expected_hash: str, now: datetime | None = None) -> CaptureArtifact:
        artifact = self.captures.load(path)
        links = tuple(item for item in artifact.metadata.links if item.path != target_path)
        if len(links) == len(artifact.metadata.links):
            raise CaptureError("link_not_found", "Capture link was not found.")
        return self.captures.save(artifact, replace(artifact.metadata, links=links, updated_at=utc_now(now).isoformat()), expected_hash=expected_hash)


@dataclass(frozen=True, slots=True)
class CaptureExperimentMapping:
    field_name: str
    measure_id: str
    phase_id: str


def capture_as_experiment_observation(
    capture: CaptureArtifact,
    experiment: ExperimentArtifact,
    mapping: CaptureExperimentMapping,
) -> Observation:
    if capture.metadata.exclude_from_experiments:
        raise CaptureError("experiment_excluded", "Capture is excluded from experiment analysis.")
    value = next((item for item in capture.metadata.derived_values if item.field_name == mapping.field_name), None)
    if value is None:
        raise CaptureError("field_not_found", "Mapped capture field was not found.")
    if value.status not in {"confirmed", "corrected"}:
        raise CaptureError("confirmation_required", "Estimated values require visible confirmation before experiment mapping.")
    if not isinstance(value.value, (str, int, float, bool)) or value.value is None:
        raise CaptureError("invalid_measurement", "Mapped capture field has no confirmed measurable value.")
    observed_at = datetime.fromisoformat(capture.metadata.event_at)
    return create_observation(
        experiment.metadata,
        measure_id=mapping.measure_id,
        phase_id=mapping.phase_id,
        observed_at=observed_at,
        state="measured",
        value=value.value,
        note=f"Explicitly mapped from capture field {mapping.field_name}; source retained as {value.source}.",
        source_refs=(SourceReference(capture.path, "rich-capture", capture.content_hash),),
        context=(capture.metadata.capture_type, value.source, value.status),
    )
