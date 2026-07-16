from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import CaptureError, DerivedValue
from lifeos.captures.domains import ExerciseDetails, ExerciseSet, FoodComponent, MealDetails
from lifeos.captures.enrichment import (
    CaptureEnrichmentService,
    EnrichmentCapabilities,
    EnrichmentRequest,
    EnrichmentResult,
)
from lifeos.captures.safety import evaluate_capture_safety

NOW = datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc)


def test_meal_allows_photo_or_sentence_and_nutrition_unknown() -> None:
    meal = MealDetails(
        components=(FoodComponent("lentil soup"),),
        nutrition=(DerivedValue("calories", None, "kcal", "unknown"),),
    )
    assert meal.nutrition[0].value is None
    with pytest.raises(CaptureError):
        FoodComponent("bread", source="image-estimate", confirmed=True)


def test_uncertain_nutrition_preserves_range_source_and_rejection(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(
        title="Dinner", capture_type="meal", description="plate photo", now=NOW
    )
    estimate = DerivedValue("calories", None, "kcal", "image-estimate", "low", 450, 800)
    service = CaptureEnrichmentService(captures=captures)
    applied = service.apply(
        capture.path,
        EnrichmentResult(suggestions=(estimate,)),
        expected_hash=capture.content_hash,
        now=NOW,
    )
    rejected = service.decide_value(
        applied.path, "calories", "reject", expected_hash=applied.content_hash, now=NOW
    )
    value = rejected.metadata.derived_values[0]
    assert (
        value.status == "rejected" and value.range_low == 450 and value.source == "image-estimate"
    )


def test_automated_transcript_can_be_corrected_without_overwriting_source(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(title="Voice note", capture_type="attachment", now=NOW)
    suggestion = DerivedValue(
        "transcript",
        "Meet at tree",
        None,
        "transcription",
        "low",
        assumptions=("Automated transcript may contain recognition errors.",),
    )
    service = CaptureEnrichmentService(captures=captures)
    applied = service.apply(
        capture.path,
        EnrichmentResult(suggestions=(suggestion,)),
        expected_hash=capture.content_hash,
        now=NOW,
    )
    corrected = service.decide_value(
        applied.path,
        "transcript",
        "correct",
        expected_hash=applied.content_hash,
        corrected_value="Meet at three",
        now=NOW,
    )
    value = corrected.metadata.derived_values[0]
    assert value.value == "Meet at three"
    assert value.status == "corrected"
    assert value.source == "transcription"


def test_planned_workout_never_counts_as_completed_by_time() -> None:
    planned = ExerciseDetails(
        "strength",
        "planned",
        start_at="2026-07-16T09:00:00+00:00",
        sequence=(ExerciseSet("squat", repetitions=5),),
    )
    performed = ExerciseDetails("strength", "modified", duration_minutes=30)
    skipped = ExerciseDetails("running", "skipped")
    assert not planned.counts_as_completed
    assert performed.counts_as_completed
    assert not skipped.counts_as_completed


def test_no_provider_fallback_parses_only_explicit_exercise_fields(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(
        title="Run", capture_type="exercise", description="Running 5 km for 31 minutes", now=NOW
    )
    service = CaptureEnrichmentService(captures=captures)
    result = service.preview(capture)
    assert result.exercise is not None
    assert result.exercise.distance == 5
    assert result.exercise.duration_minutes == 31
    assert result.suggestions == ()


def test_urgent_safety_message_stops_normal_enrichment(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(
        title="Workout",
        capture_type="exercise",
        description="Chest pain and fainting during the set",
        now=NOW,
    )
    result = CaptureEnrichmentService(captures=captures).preview(capture)
    assert result.safety_messages[0].level == "urgent"
    assert result.safety_messages[0].stop_enrichment
    assert result.exercise is None


def test_food_allergen_language_is_uncertain_and_not_proof() -> None:
    messages = evaluate_capture_safety("meal", "possible allergy after restaurant meal")
    assert messages[0].level == "caution"
    assert "cannot confirm" in messages[0].message


class TimeoutProvider:
    capabilities = EnrichmentCapabilities("fixture", "fixture", False)

    def enrich(
        self, request: EnrichmentRequest, *, timeout_seconds: float | None
    ) -> EnrichmentResult:
        raise TimeoutError


class MalformedProvider:
    capabilities = EnrichmentCapabilities("fixture", "fixture", True)

    def enrich(
        self, request: EnrichmentRequest, *, timeout_seconds: float | None
    ) -> EnrichmentResult:
        return "bad"  # type: ignore[return-value]


def test_provider_timeout_uses_no_provider_fallback(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = captures.create(
        title="Walk", capture_type="exercise", description="walk 20 minutes", now=NOW
    )
    result = CaptureEnrichmentService(captures=captures, provider=TimeoutProvider()).preview(
        capture, allow_external=True
    )
    assert result.exercise is not None
    assert "timed out" in result.explanation


def test_protected_capture_denies_external_processing_and_malformed_output(tmp_path: Path) -> None:
    captures = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    protected = captures.create(
        title="Private meal",
        capture_type="meal",
        privacy_scope="protected",
        sensitive=True,
        now=NOW,
    )
    service = CaptureEnrichmentService(captures=captures, provider=TimeoutProvider())
    with pytest.raises(CaptureError) as blocked:
        service.preview(protected)
    assert blocked.value.code == "sensitive_content_blocked"
    ordinary = captures.create(title="Meal", capture_type="meal", now=NOW)
    with pytest.raises(CaptureError) as malformed:
        CaptureEnrichmentService(captures=captures, provider=MalformedProvider()).preview(ordinary)
    assert malformed.value.code == "malformed_provider_output"
