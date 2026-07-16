from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentPhase,
    ExperimentProtocol,
    MeasureDefinition,
    analyze_experiment,
    build_visual_model,
    compare_experiments,
    create_observation,
    load_experiment_index,
    rebuild_experiment_index,
    record_conclusion,
    save_analysis,
)

NOW = datetime(2026, 7, 16, 9, tzinfo=timezone.utc)


def protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        question="Does schedule B relate to focus?",
        hypothesis="B has higher focus",
        rationale="compare",
        intervention="Use schedule B",
        constants=("same material",),
        comparison="schedule A",
        baseline_requirements="3 days",
        outcome_measures=(
            MeasureDefinition(
                "focus", "Focus", "rating", "primary", "daily", valid_min=1, valid_max=10
            ),
            MeasureDefinition(
                "adherence",
                "Followed schedule",
                "completion",
                "adherence",
                "daily",
                aggregation="rate",
            ),
            MeasureDefinition(
                "notes", "Context notes", "qualitative", "contextual", "daily", aggregation="none"
            ),
        ),
        phases=(
            ExperimentPhase("a", "Schedule A", "baseline", "2026-07-16", "2026-07-18"),
            ExperimentPhase("b", "Schedule B", "intervention", "2026-07-19", "2026-07-21"),
        ),
        adherence_expectation="all days",
        confounders=("sleep",),
        risks=(),
        stop_rules=(),
        success_criteria=("higher mean",),
        failure_criteria=("not higher",),
        inconclusive_criteria=("missing",),
        schedule={"timezone": "UTC", "time": "20:00"},
    )


def seeded(tmp_path: Path):
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    item = api.create(
        title="Schedules", description="", category="study", protocol=protocol(), now=NOW
    )
    values = [("a", 5.0), ("a", 6.0), ("a", None), ("b", 7.0), ("b", 8.0), ("b", 9.0)]
    for index, (phase, value) in enumerate(values):
        state = "not-measured" if value is None else "measured"
        obs = create_observation(
            item.metadata,
            measure_id="focus",
            phase_id=phase,
            observed_at=NOW + timedelta(days=index),
            state=state,
            value=value,
            note="missing" if value is None else "",
        )
        item = api.append_observation(
            item.path, obs, expected_hash=item.content_hash, now=NOW + timedelta(days=index)
        )
    for index, phase in enumerate(("a", "a", "b", "b")):
        obs = create_observation(
            item.metadata,
            measure_id="adherence",
            phase_id=phase,
            observed_at=NOW + timedelta(days=index),
            state="measured",
            value=index != 1,
        )
        item = api.append_observation(
            item.path, obs, expected_hash=item.content_hash, now=NOW + timedelta(days=index)
        )
    note = create_observation(
        item.metadata,
        measure_id="notes",
        phase_id="b",
        observed_at=NOW,
        state="measured",
        value="Travel day changed the context.",
        context=("possible confounder",),
    )
    item = api.append_observation(item.path, note, expected_hash=item.content_hash, now=NOW)
    return api, item


def test_analysis_preserves_missingness_raw_ids_and_noncausal_limitations(tmp_path: Path) -> None:
    api, item = seeded(tmp_path)
    analysis = analyze_experiment(item, now=NOW)
    assert analysis.evidence_kind == "descriptive"
    assert analysis.status == "confounded"
    focus = next(summary for summary in analysis.summaries if summary.get("measure_id") == "focus")
    assert focus["baseline"]["mean"] == 5.5
    assert focus["intervention"]["mean"] == 8.0
    assert focus["change_from_baseline"] == 2.5
    completeness = analysis.summaries[0]
    assert completeness["missing_count"] == 1
    assert any("does not establish causation" in item for item in analysis.limitations)
    saved = save_analysis(api, item, expected_hash=item.content_hash, now=NOW)
    concluded = record_conclusion(
        api,
        saved,
        conclusion="mixed",
        notes="Focus improved but travel confounded the comparison.",
        follow_up_decisions=("repeat",),
        expected_hash=saved.content_hash,
        now=NOW,
    )
    assert concluded.metadata.conclusion == "mixed"


def test_insufficient_analysis_and_visual_fallback(tmp_path: Path) -> None:
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    item = api.create(
        title="Sparse", description="", category="study", protocol=protocol(), now=NOW
    )
    skipped = create_observation(
        item.metadata,
        measure_id="focus",
        phase_id="a",
        observed_at=NOW,
        state="skipped",
        note="forgot",
    )
    item = api.append_observation(item.path, skipped, expected_hash=item.content_hash, now=NOW)
    analysis = analyze_experiment(item, now=NOW)
    assert analysis.status == "insufficient-evidence"
    assert all(summary.get("mean") != 0 for summary in analysis.summaries)
    visual = build_visual_model(item, now=NOW)
    assert visual["missing_indicators"] == [skipped.observation_id]
    assert "canonical experiment note" in visual["render_fallback"]


def test_rebuild_handles_rename_runtime_deletion_duplicates_interrupt_and_large_history(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / ".lifeos"
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=runtime)
    created = []
    for index in range(105):
        created.append(
            api.create(
                title=f"Experiment {index}",
                description="",
                category="study",
                protocol=protocol(),
                now=NOW + timedelta(seconds=index),
            )
        )
    interrupted = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=10, interrupt_after=20
    )
    assert interrupted.state == "interrupted"
    assert Path(interrupted.checkpoint_path).exists()
    report = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=25)
    assert report.state == "ready" and len(report.entries) == 105
    shutil.rmtree(runtime / "experiments")
    assert load_experiment_index(runtime_dir=runtime).state == "missing-index"
    first = created[0]
    old = tmp_path / first.path
    renamed = old.with_name("renamed-experiment.md")
    old.rename(renamed)
    rebuilt = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime)
    assert any(entry.path.endswith("renamed-experiment.md") for entry in rebuilt.entries)
    duplicate = old
    duplicate.write_text(renamed.read_text())
    duplicated = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime)
    assert any(item["code"] == "duplicate_identity" for item in duplicated.diagnostics)


def test_lineage_and_incompatible_comparison_warning(tmp_path: Path) -> None:
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    first = api.create(
        title="First", description="", category="study", protocol=protocol(), now=NOW
    )
    repeat = api.clone(first.path, now=NOW + timedelta(seconds=1))
    report = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    comparison = compare_experiments(
        report.entries, first.metadata.experiment_id, repeat.metadata.experiment_id
    )
    assert comparison["compatible"] is True
    assert repeat.metadata.repeated_from_experiment_id == first.metadata.experiment_id
