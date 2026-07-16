from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import ArtifactLink, DerivedValue
from lifeos.captures.visualization import build_capture_visualization

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def test_visualizations_remain_inspectable_and_preserve_missing_values(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    meal = service.create(title="Lunch", capture_type="meal", description="Soup", now=NOW)
    meal = service.save(
        meal,
        replace(
            meal.metadata,
            derived_values=(DerivedValue("calories", 350, "kcal", "image-estimate", "low"),),
            links=(ArtifactLink("experiments/soup.md", "evidence", "experiment"),),
        ),
        expected_hash=meal.content_hash,
    )
    exercise = service.create(title="Walk", capture_type="exercise", now=NOW)
    exercise = service.save(
        exercise,
        replace(
            exercise.metadata,
            domain_data={
                "exercise": {
                    "outcome": "performed",
                    "duration_minutes": None,
                    "distance": 2.5,
                    "distance_unit": "km",
                }
            },
        ),
        expected_hash=exercise.content_hash,
    )

    view = build_capture_visualization(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")

    assert view.counts_by_type == {"exercise": 1, "meal": 1}
    assert view.activity_calendar == {"2026-07-16": 2}
    assert view.timeline[0].path.endswith(".md")
    assert sum(item.suggested_value_count for item in view.timeline) == 1
    assert view.exercise_trends[0].duration_minutes is None
    assert "duration_minutes" in view.exercise_trends[0].missing_fields
    assert view.missing_data["exercise_duration"] == 1
    assert view.experiment_linked[0]["experiment_path"] == "experiments/soup.md"
    assert "good" not in str(view.to_dict()).casefold()
    assert "bad" not in str(view.to_dict()).casefold()


def test_visualizations_are_bounded_and_filterable(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    for index in range(4):
        service.create(title=f"Capture {index}", capture_type="attachment", now=NOW)
    view = build_capture_visualization(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        capture_types=frozenset({"attachment"}),
        max_points=2,
    )
    assert len(view.timeline) == 2
    assert view.counts_by_type == {"attachment": 2}
    assert view.warnings == ("View is bounded to the newest 2 matching captures.",)
