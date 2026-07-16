"""Timezone-safe, phase-relative experiment observation scheduling."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import ExperimentError, ExperimentMetadata, MeasureDefinition


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    due_at: str
    opens_at: str
    closes_at: str
    measure_id: str
    phase_id: str
    status: Literal["upcoming", "open", "overdue", "paused"]

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ExperimentError(
            "invalid_timezone", "Experiment schedule timezone is unknown.", {"timezone": name}
        ) from exc


def _days_for_measure(
    measure: MeasureDefinition, start: date, end: date, selected_days: tuple[int, ...]
) -> tuple[date, ...]:
    result: list[date] = []
    current = start
    while current <= end:
        cadence = measure.cadence.casefold()
        include = cadence in {"daily", "before-intervention", "after-intervention"}
        if cadence == "weekly":
            include = current.weekday() == 0
        if cadence == "selected-days":
            include = current.weekday() in selected_days
        if cadence in {"once", "end-only"}:
            include = current == end
        if include:
            result.append(current)
        current += timedelta(days=1)
    return tuple(result)


def _schedule_int(schedule: Mapping[str, object], key: str, default: int) -> int:
    raw = schedule.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ExperimentError("invalid_schedule", f"Schedule {key} must be an integer.")
    try:
        return int(raw)
    except ValueError as exc:
        raise ExperimentError("invalid_schedule", f"Schedule {key} must be an integer.") from exc


def _selected_days(schedule: Mapping[str, object]) -> tuple[int, ...]:
    raw = schedule.get("weekdays", (0, 1, 2, 3, 4, 5, 6))
    if not isinstance(raw, (list, tuple)):
        raise ExperimentError("invalid_schedule", "Schedule weekdays must be a list.")
    result: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ExperimentError("invalid_schedule", "Schedule weekdays must contain integers.")
        try:
            day = int(item)
        except ValueError as exc:
            raise ExperimentError(
                "invalid_schedule", "Schedule weekdays must contain integers."
            ) from exc
        if day < 0 or day > 6:
            raise ExperimentError("invalid_schedule", "Schedule weekdays must be between 0 and 6.")
        result.append(day)
    return tuple(result)


def build_collection_windows(
    metadata: ExperimentMetadata, *, now: datetime
) -> tuple[CollectionWindow, ...]:
    schedule: Mapping[str, object] = metadata.protocol.schedule
    timezone_name = str(schedule.get("timezone", "UTC"))
    tz = _timezone(timezone_name)
    if now.tzinfo is None:
        raise ExperimentError(
            "invalid_timestamp", "Schedule evaluation requires a timezone-aware timestamp."
        )
    local_now = now.astimezone(tz)
    due_time = time.fromisoformat(str(schedule.get("time", "20:00")))
    window_minutes = _schedule_int(schedule, "window_minutes", 120)
    grace_minutes = _schedule_int(schedule, "grace_minutes", 60)
    selected_days = _selected_days(schedule)
    windows: list[CollectionWindow] = []
    for phase in metadata.protocol.phases:
        start = date.fromisoformat(phase.start_date)
        end = date.fromisoformat(phase.end_date)
        for measure in metadata.protocol.outcome_measures:
            for day in _days_for_measure(measure, start, end, selected_days):
                due = datetime.combine(day, due_time, tzinfo=tz)
                opens = due - timedelta(minutes=window_minutes)
                closes = due + timedelta(minutes=grace_minutes)
                if metadata.state == "paused":
                    status: Literal["upcoming", "open", "overdue", "paused"] = "paused"
                elif local_now < opens:
                    status = "upcoming"
                elif local_now <= closes:
                    status = "open"
                else:
                    status = "overdue"
                windows.append(
                    CollectionWindow(
                        due.isoformat(),
                        opens.isoformat(),
                        closes.isoformat(),
                        measure.measure_id,
                        phase.phase_id,
                        status,
                    )
                )
    return tuple(sorted(windows, key=lambda item: (item.due_at, item.measure_id)))


def due_windows(metadata: ExperimentMetadata, *, now: datetime) -> tuple[CollectionWindow, ...]:
    recorded = {
        (item.measure_id, item.phase_id, item.observed_at[:10]) for item in metadata.observations
    }
    return tuple(
        window
        for window in build_collection_windows(metadata, now=now)
        if window.status in {"open", "overdue"}
        and (window.measure_id, window.phase_id, window.due_at[:10]) not in recorded
    )
