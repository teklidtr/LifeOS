"""Rebuildable, inspectable summaries for rich-capture browsing surfaces."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from .artifact import CaptureArtifactService
from .contracts import CaptureArtifact


@dataclass(frozen=True, slots=True)
class CaptureTimelinePoint:
    capture_id: str
    path: str
    event_at: str
    title: str
    capture_type: str
    state: str
    attachment_count: int
    confirmed_value_count: int
    suggested_value_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExerciseTrendPoint:
    capture_id: str
    path: str
    event_at: str
    outcome: str
    duration_minutes: float | None
    distance: float | None
    distance_unit: str | None
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CaptureVisualization:
    timeline: tuple[CaptureTimelinePoint, ...]
    counts_by_type: dict[str, int]
    counts_by_state: dict[str, int]
    activity_calendar: dict[str, int]
    processing_status: dict[str, int]
    exercise_trends: tuple[ExerciseTrendPoint, ...]
    experiment_linked: tuple[dict[str, object], ...]
    missing_data: dict[str, int]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "timeline": [item.to_dict() for item in self.timeline],
            "counts_by_type": dict(self.counts_by_type),
            "counts_by_state": dict(self.counts_by_state),
            "activity_calendar": dict(self.activity_calendar),
            "processing_status": dict(self.processing_status),
            "exercise_trends": [item.to_dict() for item in self.exercise_trends],
            "experiment_linked": [dict(item) for item in self.experiment_linked],
            "missing_data": dict(self.missing_data),
            "warnings": list(self.warnings),
        }


def _domain_mapping(capture: CaptureArtifact) -> dict[str, object]:
    data = capture.metadata.domain_data
    return data if isinstance(data, dict) else {}


def build_capture_visualization(
    *,
    vault_root: Path,
    runtime_dir: Path,
    capture_types: frozenset[str] | None = None,
    states: frozenset[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    max_points: int = 500,
) -> CaptureVisualization:
    """Build bounded views from canonical Markdown without mutating it.

    Unknown values stay ``None`` and are counted as missing instead of becoming
    zero. The return value intentionally contains raw paths and capture IDs so a
    chart can always lead back to the underlying record.
    """

    if type(max_points) is not int or max_points < 1 or max_points > 5_000:
        raise ValueError("max_points must be between 1 and 5000.")
    service = CaptureArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    captures = service.list(capture_types=capture_types, states=states)
    selected: list[CaptureArtifact] = []
    for capture in captures:
        event_day = date.fromisoformat(capture.metadata.event_at[:10])
        if start is not None and event_day < start:
            continue
        if end is not None and event_day > end:
            continue
        selected.append(capture)
    selected = selected[:max_points]

    type_counts = Counter(item.metadata.capture_type for item in selected)
    state_counts = Counter(item.metadata.state for item in selected)
    calendar_counts = Counter(item.metadata.event_at[:10] for item in selected)
    processing: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    timeline: list[CaptureTimelinePoint] = []
    exercise: list[ExerciseTrendPoint] = []
    experiment_links: list[dict[str, object]] = []

    for capture in selected:
        meta = capture.metadata
        processing[f"extraction:{meta.extraction_status}"] += 1
        processing[f"enrichment:{meta.enrichment_status}"] += 1
        confirmed = sum(value.status in {"confirmed", "corrected"} for value in meta.derived_values)
        suggested = sum(value.status == "suggested" for value in meta.derived_values)
        timeline.append(
            CaptureTimelinePoint(
                meta.capture_id,
                capture.path,
                meta.event_at,
                meta.title,
                meta.capture_type,
                meta.state,
                len(meta.attachments),
                confirmed,
                suggested,
            )
        )
        if not meta.description and not meta.attachments:
            missing["description_or_attachment"] += 1
        if suggested:
            missing["unconfirmed_suggestions"] += suggested
        if meta.extraction_status in {"failed", "stale"}:
            missing["extraction_attention"] += 1
        if meta.enrichment_status in {"failed", "stale"}:
            missing["enrichment_attention"] += 1

        for link in meta.links:
            if link.artifact_type == "experiment":
                experiment_links.append(
                    {
                        "capture_id": meta.capture_id,
                        "capture_path": capture.path,
                        "event_at": meta.event_at,
                        "experiment_path": link.path,
                        "relation": link.relation,
                    }
                )

        if meta.capture_type != "exercise":
            continue
        domain = _domain_mapping(capture)
        exercise_data = domain.get("exercise", domain)
        exercise_data = exercise_data if isinstance(exercise_data, dict) else {}
        duration = exercise_data.get("duration_minutes")
        distance = exercise_data.get("distance")
        outcome = exercise_data.get("outcome", "unknown")
        duration_value = (
            float(duration)
            if isinstance(duration, (int, float)) and not isinstance(duration, bool)
            else None
        )
        distance_value = (
            float(distance)
            if isinstance(distance, (int, float)) and not isinstance(distance, bool)
            else None
        )
        missing_fields: list[str] = []
        if duration_value is None:
            missing_fields.append("duration_minutes")
            missing["exercise_duration"] += 1
        if outcome == "unknown":
            missing_fields.append("outcome")
            missing["exercise_outcome"] += 1
        exercise.append(
            ExerciseTrendPoint(
                meta.capture_id,
                capture.path,
                meta.event_at,
                str(outcome),
                duration_value,
                distance_value,
                str(exercise_data["distance_unit"])
                if exercise_data.get("distance_unit") is not None
                else None,
                tuple(missing_fields),
            )
        )

    warnings: list[str] = []
    if len(captures) > max_points:
        warnings.append(f"View is bounded to the newest {max_points} matching captures.")
    if any(point.duration_minutes is None for point in exercise):
        warnings.append(
            "Exercise trend omits unknown duration values rather than plotting them as zero."
        )
    return CaptureVisualization(
        tuple(timeline),
        dict(sorted(type_counts.items())),
        dict(sorted(state_counts.items())),
        dict(sorted(calendar_counts.items())),
        dict(sorted(processing.items())),
        tuple(exercise),
        tuple(experiment_links),
        dict(sorted(missing.items())),
        tuple(warnings),
    )
