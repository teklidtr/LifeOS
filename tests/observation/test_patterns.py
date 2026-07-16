from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.observation import (
    ObservationError,
    ObservationRecord,
    analyze_activity_pattern,
    analyze_numeric_pattern,
    load_observations,
)


def test_load_observations_from_journal_frontmatter(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "2026-07-01.md").write_text(
        "---\ndate: 2026-07-01\nmetrics:\n  energy: 4\n  sleep_hours: 8\n"
        "activities:\n  - running\n---\nA good day.\n",
        encoding="utf-8",
    )

    records = load_observations(tmp_path)

    assert records == (
        ObservationRecord(
            date(2026, 7, 1),
            "journal/2026-07-01.md",
            {"energy": 4.0, "sleep_hours": 8.0},
            ("running",),
        ),
    )


def test_numeric_pattern_is_candidate_and_noncausal() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, day),
            f"journal/{day}.md",
            {"sleep": float(day), "energy": float(day * 2)},
            (),
        )
        for day in range(1, 7)
    )

    report = analyze_numeric_pattern(
        records=records,
        outcome="energy",
        factor="sleep",
        min_samples=5,
    )

    candidate = report.candidates[0]
    assert candidate.status == "candidate"
    assert candidate.direction == "positive"
    assert candidate.effect == 1.0
    assert "not evidence of causation" in candidate.caveats[0]


def test_numeric_pattern_reports_insufficient_evidence() -> None:
    records = (
        ObservationRecord(date(2026, 7, 1), "journal/1.md", {"sleep": 7.0, "energy": 3.0}, ()),
    )

    report = analyze_numeric_pattern(records=records, outcome="energy", factor="sleep")

    assert report.candidates == ()
    assert "Only 1 paired observations" in report.gaps[0]


def test_activity_pattern_compares_both_groups() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, index + 1),
            f"journal/{index}.md",
            {"energy": value},
            ("running",) if index < 3 else (),
        )
        for index, value in enumerate((5.0, 5.0, 4.0, 2.0, 2.0, 3.0))
    )

    report = analyze_activity_pattern(
        records=records,
        outcome="energy",
        activity="running",
        min_group_size=3,
    )

    assert report.candidates[0].direction == "higher"
    assert report.candidates[0].status == "candidate"
    assert "prompt for reflection" in report.candidates[0].caveats[1]


def test_numeric_pattern_rejects_the_same_metric_on_both_axes() -> None:
    with pytest.raises(ObservationError, match="different metrics"):
        analyze_numeric_pattern(
            records=(),
            outcome="energy",
            factor=" Energy ",
        )


@pytest.mark.parametrize(
    ("outcome", "activity"),
    [("", "running"), ("energy", " ")],
)
def test_activity_pattern_rejects_blank_inputs(outcome: str, activity: str) -> None:
    with pytest.raises(ObservationError, match="non-empty"):
        analyze_activity_pattern(
            records=(),
            outcome=outcome,
            activity=activity,
        )


def test_numeric_pattern_normalizes_metric_names() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, day),
            f"journal/2026-07-{day:02d}.md",
            {"sleep": float(day), "energy": float(day)},
            (),
        )
        for day in range(1, 6)
    )

    report = analyze_numeric_pattern(
        records=records,
        outcome=" energy ",
        factor=" sleep ",
    )

    assert report.outcome == "energy"
    assert report.factor == "sleep"
    assert report.candidates


def test_activity_pattern_normalizes_requested_names() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, day),
            f"journal/2026-07-{day:02d}.md",
            {"energy": 5.0 if day <= 3 else 1.0},
            ("running",) if day <= 3 else (),
        )
        for day in range(1, 7)
    )

    report = analyze_activity_pattern(
        records=records,
        outcome=" energy ",
        activity=" running ",
    )

    assert report.outcome == "energy"
    assert report.factor == "running"
    assert report.candidates


def test_observation_date_rejects_datetime_metadata(tmp_path: Path) -> None:
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "entry.md").write_text(
        "---\ndate: 2026-07-01T12:00:00\nmetrics:\n  energy: 3\n---\n",
        encoding="utf-8",
    )

    with pytest.raises(ObservationError, match="date must be an ISO date"):
        load_observations(tmp_path)


def _activity_records(
    tagged: tuple[float, ...],
    untagged: tuple[float, ...],
    *,
    unit: str = "points",
) -> tuple[ObservationRecord, ...]:
    values = (*tagged, *untagged)
    return tuple(
        ObservationRecord(
            date(2026, 7, index + 1),
            f"journal/{index + 1}.md",
            {"energy": value},
            ("running",) if index < len(tagged) else (),
            {"energy": unit},
            {"energy": "daily self-rating"},
        )
        for index, value in enumerate(values)
    )


def test_activity_effect_is_scale_aware() -> None:
    compact = analyze_activity_pattern(
        records=_activity_records((11.0, 12.0, 13.0), (10.0, 11.0, 12.0)),
        outcome="energy",
        activity="running",
    )
    wide_scale = analyze_activity_pattern(
        records=_activity_records((101.0, 151.0, 201.0), (100.0, 150.0, 200.0)),
        outcome="energy",
        activity="running",
    )

    assert compact.candidates[0].raw_effect == 1.0
    assert compact.candidates[0].standardized_effect > 0.5
    assert wide_scale.candidates == ()
    assert "scale-adjusted" in wide_scale.gaps[0]


def test_numeric_pattern_withholds_zero_variance() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, day),
            f"journal/{day}.md",
            {"sleep": 8.0, "energy": float(day)},
            (),
        )
        for day in range(1, 7)
    )

    report = analyze_numeric_pattern(records=records, outcome="energy", factor="sleep")

    assert report.candidates == ()
    assert report.gaps == ("Factor variance is too small to estimate an association.",)


def test_strong_activity_effect_with_wide_uncertainty_is_low_strength() -> None:
    report = analyze_activity_pattern(
        records=_activity_records((10.0, 11.0, 12.0), (1.0, 2.0, 3.0)),
        outcome="energy",
        activity="running",
    )

    candidate = report.candidates[0]
    assert candidate.evidence_strength == "low"
    assert candidate.uncertainty_interval[0] < candidate.uncertainty_interval[1]
    assert "not a causal conclusion" in candidate.caveats[1]


def test_incompatible_metric_units_withhold_analysis() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 7, day),
            f"journal/{day}.md",
            {"sleep": float(day), "energy": float(day)},
            (),
            {"sleep": "hours", "energy": "points" if day < 4 else "percent"},
            {"sleep": "nightly duration", "energy": "daily self-rating"},
        )
        for day in range(1, 7)
    )

    report = analyze_numeric_pattern(records=records, outcome="energy", factor="sleep")

    assert report.candidates == ()
    assert "incompatible" in report.gaps[0]


def test_duplicate_dates_are_diagnosed_deterministically() -> None:
    records = (
        ObservationRecord(date(2026, 7, 1), "journal/a.md", {"sleep": 7.0, "energy": 3.0}, ()),
        ObservationRecord(date(2026, 7, 1), "journal/b.md", {"sleep": 8.0, "energy": 4.0}, ()),
    )

    report = analyze_numeric_pattern(records=records, outcome="energy", factor="sleep")

    assert report.candidates == ()
    assert report.gaps == (
        "Duplicate observation dates must be resolved before analysis: 2026-07-01.",
    )


def test_candidate_reports_missingness_date_range_freshness_and_uncertainty() -> None:
    records = tuple(
        ObservationRecord(
            date(2026, 1, day),
            f"journal/{day}.md",
            {"sleep": float(day), "energy": float(day * 2)},
            (),
        )
        for day in range(1, 7)
    ) + (ObservationRecord(date(2026, 1, 7), "journal/7.md", {"energy": 7.0}, ()),)

    report = analyze_numeric_pattern(
        records=records,
        outcome="energy",
        factor="sleep",
        as_of=date(2026, 7, 1),
    )

    candidate = report.candidates[0]
    assert candidate.missing_count == 1
    assert candidate.date_range == ("2026-01-01", "2026-01-06")
    assert candidate.freshness_days == 176
    assert (
        candidate.uncertainty_interval[0] <= candidate.effect <= candidate.uncertainty_interval[1]
    )
    assert "Repeated measurements" in candidate.quality_notes[-1]
