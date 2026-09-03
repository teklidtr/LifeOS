from __future__ import annotations

import json
import shutil

import pytest

import lifeos.experiments.history as experiment_history
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


def _seed_experiment_history(tmp_path: Path, count: int):
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    created = [
        api.create(
            title=f"Experiment {index}",
            description="",
            category="study",
            protocol=protocol(),
            now=NOW + timedelta(seconds=index),
        )
        for index in range(count)
    ]
    return api, created


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


def test_large_history_rebuild_interrupts_and_completes(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _api, _created = _seed_experiment_history(tmp_path, 105)

    interrupted = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=10, interrupt_after=20
    )
    assert interrupted.state == "interrupted"
    assert Path(interrupted.checkpoint_path).exists()

    report = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=25)
    assert report.state == "ready"
    assert len(report.entries) == 105


def test_runtime_deletion_marks_experiment_index_missing(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _api, _created = _seed_experiment_history(tmp_path, 2)
    report = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime)
    assert report.state == "ready"

    shutil.rmtree(runtime / "experiments")
    assert load_experiment_index(runtime_dir=runtime).state == "missing-index"


def test_rebuild_tracks_renamed_experiment_artifact(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _api, created = _seed_experiment_history(tmp_path, 2)
    old = tmp_path / created[0].path
    renamed = old.with_name("renamed-experiment.md")
    old.rename(renamed)

    rebuilt = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime)
    assert any(entry.path.endswith("renamed-experiment.md") for entry in rebuilt.entries)


def test_rebuild_reports_duplicate_experiment_identity(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"
    _api, created = _seed_experiment_history(tmp_path, 2)
    source = tmp_path / created[0].path
    duplicate = source.with_name("duplicate-experiment.md")
    duplicate.write_text(source.read_text())

    rebuilt = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime)
    assert any(item["code"] == "duplicate_identity" for item in rebuilt.diagnostics)


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


def _experiment_source_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted((root / "experiments").rglob("*.md"))
    }


def test_rebuild_resumes_verified_experiment_progress_and_bounds_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / ".lifeos"
    _api, _created = _seed_experiment_history(tmp_path, 3)
    canonical_before = _experiment_source_bytes(tmp_path)
    processed: list[str] = []
    real_parse = experiment_history.parse_experiment

    def recording_parse(path: Path, relative_path: str, content: str):
        processed.append(relative_path)
        return real_parse(path, relative_path, content)

    monkeypatch.setattr(experiment_history, "parse_experiment", recording_parse)

    first = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    second = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    third = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )

    assert [len(first.entries), len(second.entries), len(third.entries)] == [1, 2, 3]
    assert len(processed) == 3
    assert len(set(processed)) == 3
    checkpoint = runtime / "experiments" / "rebuild-checkpoint.json"
    assert json.loads(checkpoint.read_text())["next_index"] == 3

    resumed = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=1)
    assert resumed.state == "ready"
    assert len(resumed.entries) == 3
    assert not checkpoint.exists()
    assert _experiment_source_bytes(tmp_path) == canonical_before

    shutil.rmtree(runtime / "experiments")
    fresh = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=1)
    assert resumed.entries == fresh.entries
    assert resumed.diagnostics == fresh.diagnostics


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        '{"schema": 999, "next_index": 1}',
        '{"schema": 2, "source_signature": "sha256:forged"}',
    ],
)
def test_rebuild_discards_invalid_experiment_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    runtime = tmp_path / ".lifeos"
    _api, _created = _seed_experiment_history(tmp_path, 2)
    first = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert first.state == "interrupted"
    checkpoint = runtime / "experiments" / "rebuild-checkpoint.json"
    checkpoint.write_text(payload)

    processed: list[str] = []
    real_parse = experiment_history.parse_experiment

    def recording_parse(path: Path, relative_path: str, content: str):
        processed.append(relative_path)
        return real_parse(path, relative_path, content)

    monkeypatch.setattr(experiment_history, "parse_experiment", recording_parse)
    restarted = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )

    assert restarted.state == "interrupted"
    assert len(processed) == 1
    checkpoint_data = json.loads(checkpoint.read_text())
    assert checkpoint_data["schema"] == 2
    assert checkpoint_data["next_index"] == 1
    assert isinstance(checkpoint_data["checkpoint_digest"], str)


@pytest.mark.parametrize(
    "change", ["edit", "add", "move", "delete", "duplicate", "unsupported", "malformed"]
)
def test_experiment_checkpoint_is_invalidated_when_canonical_sources_change(
    tmp_path: Path, change: str
) -> None:
    runtime = tmp_path / ".lifeos"
    api, created = _seed_experiment_history(tmp_path, 3)
    first = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert first.state == "interrupted"
    checkpoint = runtime / "experiments" / "rebuild-checkpoint.json"
    first_signature = json.loads(checkpoint.read_text())["source_signature"]
    source = tmp_path / created[0].path

    if change == "edit":
        source.write_text(source.read_text() + "\ncheckpoint source edit\n")
    elif change == "add":
        api.create(
            title="Added experiment",
            description="",
            category="study",
            protocol=protocol(),
            now=NOW + timedelta(minutes=1),
        )
    elif change == "move":
        source.rename(source.with_name("renamed-after-interruption.md"))
    elif change == "delete":
        source.unlink()
    elif change == "duplicate":
        source.with_name("duplicate-after-interruption.md").write_bytes(source.read_bytes())
    elif change == "unsupported":
        source.write_text(source.read_text().replace("schema_version: 1", "schema_version: 999", 1))
    else:
        source.write_text(
            source.read_text().replace(
                "<!-- lifeos:managed:end personal-experiment -->",
                "<!-- lifeos:managed:end broken-experiment -->",
                1,
            )
        )

    canonical_after_change = _experiment_source_bytes(tmp_path)
    restarted = rebuild_experiment_index(
        vault_root=tmp_path, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert restarted.state == "interrupted"
    second_signature = json.loads(checkpoint.read_text())["source_signature"]
    assert second_signature != first_signature

    resumed = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=1)
    assert resumed.state == "ready"
    assert _experiment_source_bytes(tmp_path) == canonical_after_change

    shutil.rmtree(runtime / "experiments")
    fresh = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=1)
    assert resumed.entries == fresh.entries
    assert resumed.diagnostics == fresh.diagnostics


def test_experiment_rebuild_empty_sources_are_ready_and_checkpoint_free(tmp_path: Path) -> None:
    runtime = tmp_path / ".lifeos"

    rebuilt = rebuild_experiment_index(vault_root=tmp_path, runtime_dir=runtime, batch_size=1)

    assert rebuilt.state == "ready"
    assert rebuilt.entries == ()
    assert rebuilt.diagnostics == ()
    assert not (runtime / "experiments" / "rebuild-checkpoint.json").exists()
