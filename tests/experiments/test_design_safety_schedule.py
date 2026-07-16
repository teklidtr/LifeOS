from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from lifeos.experiments import (
    AssistanceRequest,
    DeterministicExperimentAssistance,
    ExperimentArtifactService,
    ExperimentPhase,
    ExperimentProtocol,
    MeasureDefinition,
    assist_design,
    build_collection_windows,
    classify_safety,
    due_windows,
    evaluate_design,
    immediate_message,
)
from lifeos.retrieval.contracts import CancellationToken


def base_protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        question="Does a morning walk relate to focus?",
        hypothesis="Focus ratings will be higher after a morning walk.",
        rationale="Observe a small routine change.",
        intervention="Walk 20 minutes",
        constants=("same study time",),
        comparison="No-walk baseline",
        baseline_requirements="Seven baseline days",
        outcome_measures=(
            MeasureDefinition(
                "focus",
                "Focused study rating",
                "rating",
                "primary",
                "daily",
                valid_min=1,
                valid_max=10,
            ),
            MeasureDefinition(
                "walk-done",
                "Walk completed",
                "completion",
                "adherence",
                "daily",
                aggregation="rate",
            ),
        ),
        phases=(
            ExperimentPhase("base", "Baseline", "baseline", "2026-07-16", "2026-07-22"),
            ExperimentPhase("walk", "Walk", "intervention", "2026-07-23", "2026-07-29"),
        ),
        adherence_expectation="Five of seven days",
        confounders=("sleep",),
        risks=(),
        stop_rules=("Stop for pain",),
        success_criteria=("One-point increase",),
        failure_criteria=("No increase",),
        inconclusive_criteria=("Fewer than five observations",),
        schedule={
            "timezone": "Europe/Istanbul",
            "time": "20:00",
            "window_minutes": 120,
            "grace_minutes": 60,
        },
    )


def test_design_warnings_are_inspectable_and_not_a_score(tmp_path: Path) -> None:
    vague = replace(
        base_protocol(),
        intervention="Walk and change caffeine; use phone blocker",
        comparison="",
        baseline_requirements="",
        outcome_measures=(
            MeasureDefinition(
                "mood",
                "Mood",
                "qualitative",
                "primary",
                "monthly",
                source="retrospective memory",
                aggregation="none",
            ),
        ),
        phases=(ExperimentPhase("x", "Short", "intervention", "2026-07-16", "2026-07-17"),),
        success_criteria=(),
        inconclusive_criteria=(),
    )
    codes = {item.code for item in evaluate_design(vague)}
    assert {
        "multiple-interventions",
        "no-baseline",
        "short-duration",
        "sparse-measurement",
        "criteria-incomplete",
        "retrospective-only",
        "adherence-unmeasured",
    } <= codes
    assert all(item.explanation and item.recommendation for item in evaluate_design(vague))
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    active = api.create(
        title="Existing",
        description="",
        category="study",
        protocol=base_protocol(),
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    active = api.transition(
        active.path,
        "drafting",
        expected_hash=active.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    active = api.transition(
        active.path,
        "baseline",
        expected_hash=active.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    active = api.transition(
        active.path,
        "active",
        expected_hash=active.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert "duplicate-active-experiment" in {
        item.code for item in evaluate_design(base_protocol(), active_experiments=(active,))
    }


def test_safety_blocks_medication_and_stops_emergency_workflow() -> None:
    medication = replace(
        base_protocol(), intervention="Stop prescription medication and change dose"
    )
    classified = classify_safety(medication)
    assert classified.level == "blocked"
    assert not classified.allows_activation
    emergency = replace(
        base_protocol(), question="Does this help chest pain when I cannot breathe?"
    )
    emergency_classification = classify_safety(emergency)
    assert emergency_classification.level == "emergency"
    assert immediate_message(emergency_classification).continue_workflow is False


def test_schedule_is_timezone_safe_pause_aware_and_does_not_create_tasks(tmp_path: Path) -> None:
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    item = api.create(
        title="Schedule",
        description="",
        category="study",
        protocol=base_protocol(),
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    windows = build_collection_windows(
        item.metadata, now=datetime(2026, 7, 16, 18, tzinfo=timezone.utc)
    )
    assert windows[0].due_at.endswith("+03:00")
    assert due_windows(item.metadata, now=datetime(2026, 7, 16, 18, tzinfo=timezone.utc))
    item = api.transition(
        item.path,
        "drafting",
        expected_hash=item.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    item = api.transition(
        item.path,
        "scheduled",
        expected_hash=item.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    item = api.transition(
        item.path,
        "paused",
        expected_hash=item.content_hash,
        now=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )
    assert all(
        window.status == "paused"
        for window in build_collection_windows(
            item.metadata, now=datetime(2026, 7, 16, 18, tzinfo=timezone.utc)
        )
    )
    assert not (tmp_path / "tasks").exists()


def test_no_model_fallback_and_provider_disclosure() -> None:
    request = AssistanceRequest(
        "clarify", base_protocol(), ("goals/focus.md",), ("health details",)
    )
    fallback = assist_design(request, provider=None)
    assert fallback.state == "no-model"
    assert fallback.provider_disclosure == {"configured": False, "sent_paths": []}
    provider = DeterministicExperimentAssistance(("Use a fixed focus-rating prompt.",))
    result = assist_design(request, provider=provider, cancellation=CancellationToken())
    assert result.state == "ready"
    assert result.provider_disclosure["sent_paths"] == ["goals/focus.md"]
    assert result.provider_disclosure["adapter_key"] == "deterministic-fixture"
