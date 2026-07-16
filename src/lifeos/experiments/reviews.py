"""Contextual daily and weekly review surfaces for experiments."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lifeos.reviews.contracts import ReviewSectionSnapshot, ReviewSourceReference

from .analysis import analyze_experiment
from .artifact import ExperimentArtifactService
from .contracts import ExperimentArtifact, ExperimentError
from .scheduling import due_windows


def _source(
    artifact: ExperimentArtifact, detail: str, generated_at: str
) -> tuple["ReviewSourceReference", ...]:
    from lifeos.reviews.contracts import ReviewSourceReference

    return (ReviewSourceReference(artifact.path, artifact.content_hash, detail, generated_at),)


def daily_experiment_section(
    *, vault_root: Path, runtime_dir: Path, day: date, generated_at: datetime
) -> "ReviewSectionSnapshot":
    from lifeos.reviews.contracts import (
        ReviewItemSnapshot,
        ReviewSectionSnapshot,
        stable_fingerprint,
    )

    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    items: list[ReviewItemSnapshot] = []
    try:
        artifacts = service.list(states=frozenset({"baseline", "scheduled", "active", "paused"}))
    except ExperimentError as exc:
        return ReviewSectionSnapshot(
            "experiments-daily", "Experiments today", True, "unavailable", (), exc.message
        )
    for artifact in artifacts:
        metadata = artifact.metadata
        windows = tuple(
            window
            for window in due_windows(metadata, now=generated_at)
            if window.due_at[:10] == day.isoformat()
        )
        stop_warning = metadata.safety.level in {"caution", "blocked", "emergency"}
        amendment_pending = bool(
            metadata.amendments and metadata.amendments[-1].created_at[:10] == day.isoformat()
        )
        if not windows and not stop_warning and not amendment_pending:
            continue
        due_count = sum(window.status == "open" for window in windows)
        missed_count = sum(window.status == "overdue" for window in windows)
        detail_parts = []
        if due_count:
            detail_parts.append(f"{due_count} observation(s) due")
        if missed_count:
            detail_parts.append(f"{missed_count} observation(s) missed")
        if amendment_pending:
            detail_parts.append("protocol amendment awaiting acknowledgment")
        if stop_warning:
            detail_parts.append(f"safety state: {metadata.safety.level}")
        detail = "; ".join(detail_parts)
        fingerprint = stable_fingerprint(
            artifact.path,
            artifact.content_hash,
            day,
            *(f"{window.measure_id}:{window.phase_id}:{window.status}" for window in windows),
            metadata.safety.level,
            metadata.amendments[-1].amendment_id if amendment_pending else "",
        )
        items.append(
            ReviewItemSnapshot(
                f"experiment-day:{metadata.experiment_id}",
                "experiments-daily",
                metadata.title,
                detail,
                fingerprint,
                "ready",
                "record-observation",
                _source(artifact, detail, generated_at.isoformat()),
            )
        )
    return ReviewSectionSnapshot(
        "experiments-daily", "Experiments today", True, "ready" if items else "empty", tuple(items)
    )


def weekly_experiment_section(
    *,
    vault_root: Path,
    runtime_dir: Path,
    range_start: date,
    range_end: date,
    generated_at: datetime,
) -> "ReviewSectionSnapshot":
    from lifeos.reviews.contracts import (
        ReviewItemSnapshot,
        ReviewSectionSnapshot,
        stable_fingerprint,
    )

    service = ExperimentArtifactService(vault_root=vault_root, runtime_dir=runtime_dir)
    items: list[ReviewItemSnapshot] = []
    try:
        artifacts = service.list()
    except ExperimentError as exc:
        return ReviewSectionSnapshot(
            "experiments-weekly", "Experiment review", True, "unavailable", (), exc.message
        )
    for artifact in artifacts:
        metadata = artifact.metadata
        recently_updated = (
            range_start.isoformat() <= metadata.updated_at[:10] <= range_end.isoformat()
        )
        active = metadata.state in {"baseline", "scheduled", "active", "paused", "completed"}
        if not active and not recently_updated:
            continue
        analysis = analyze_experiment(artifact, now=generated_at)
        total = len(metadata.observations)
        missing = sum(item.state != "measured" for item in metadata.observations)
        amendments = sum(
            range_start.isoformat() <= item.created_at[:10] <= range_end.isoformat()
            for item in metadata.amendments
        )
        action = "analyze" if metadata.state == "completed" and not metadata.analyses else "open"
        detail = (
            f"State {metadata.state}; {total - missing}/{total} measured; {missing} missing or skipped; "
            f"{amendments} amendment(s) this week; analysis state {analysis.status}."
        )
        items.append(
            ReviewItemSnapshot(
                f"experiment-week:{metadata.experiment_id}",
                "experiments-weekly",
                metadata.title,
                detail,
                stable_fingerprint(artifact.path, artifact.content_hash, detail),
                "ready",
                action,
                _source(artifact, detail, generated_at.isoformat()),
            )
        )
    return ReviewSectionSnapshot(
        "experiments-weekly", "Experiment review", True, "ready" if items else "empty", tuple(items)
    )
