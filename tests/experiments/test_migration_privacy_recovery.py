from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentPhase,
    ExperimentProtocol,
    MeasureDefinition,
    SourceReference,
    apply_experiment_migration,
    audit_experiment_recovery,
    preview_experiment_context,
    preview_experiment_migration,
    rebuild_experiment_index,
)

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        question="Does a morning walk relate to focus?",
        hypothesis="Focus will be higher during the walk phase.",
        rationale="Small personal observation.",
        intervention="Walk for 20 minutes after breakfast.",
        constants=("same study block",),
        comparison="No-walk baseline.",
        baseline_requirements="Two baseline days.",
        outcome_measures=(
            MeasureDefinition(
                "focus", "Focus rating", "rating", "primary", "daily", valid_min=1, valid_max=5
            ),
            MeasureDefinition(
                "walked", "Walk completed", "completion", "adherence", "daily", aggregation="rate"
            ),
        ),
        phases=(
            ExperimentPhase("base", "Baseline", "baseline", "2026-07-16", "2026-07-17"),
            ExperimentPhase(
                "walk", "Walk", "intervention", "2026-07-18", "2026-07-21", "Morning walk"
            ),
        ),
        adherence_expectation="Record whether the walk occurred.",
        confounders=("sleep",),
        risks=(),
        stop_rules=("Stop for pain.",),
        success_criteria=("Intervention average is higher.",),
        failure_criteria=("No improvement.",),
        inconclusive_criteria=("Fewer than four focus ratings.",),
        schedule={"timezone": "Europe/Istanbul", "time": "12:00"},
    )


def legacy(title: str, start: str) -> str:
    return f"""---
type: personal-experiment-v0
title: {title}
description: Imported experiment
status: completed
category: focus
created_at: {start}T09:00:00+00:00
question: Does a morning walk relate to focus?
hypothesis: Focus will be higher during the walk phase.
intervention: Walk for 20 minutes after breakfast.
comparison: No-walk baseline.
baseline_requirements: Two baseline days.
outcome_measures:
  - measure_id: focus
    display_name: Focus rating
    kind: rating
    role: primary
    cadence: daily
    source: manual
    direction: increase
    missing_behavior: report
    aggregation: mean
phases:
  - phase_id: base
    name: Baseline
    kind: baseline
    start_date: {start}
    end_date: {start}
    intervention: ''
adherence_expectation: Record the intervention.
confounders: [sleep]
risks: []
stop_rules: [Stop for pain]
success_criteria: [Focus is higher]
failure_criteria: [Focus is not higher]
inconclusive_criteria: [Missing data]
schedule:
  timezone: Europe/Istanbul
  time: '12:00'
---

# {title}

Human legacy observations stay here.
"""


def test_migration_preview_apply_resume_and_source_hash_safety(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    (vault / "tracking").mkdir(parents=True)
    first = vault / "tracking" / "walk-a.md"
    second = vault / "tracking" / "walk-b.md"
    first.write_text(legacy("Walk A", "2026-07-16"))
    second.write_text(legacy("Walk B", "2026-07-17"))
    preview = preview_experiment_migration(vault_root=vault, runtime_dir=runtime)
    assert [item.state for item in preview.candidates] == ["ready", "ready"]
    hashes = {item.source.path: item.source.content_hash for item in preview.candidates}
    interrupted = apply_experiment_migration(
        vault_root=vault, runtime_dir=runtime, expected_source_hashes=hashes, interrupt_after=1
    )
    assert interrupted.state == "interrupted"
    assert len(interrupted.migrated) == 1
    assert first.exists() and second.exists()
    resumed = apply_experiment_migration(
        vault_root=vault, runtime_dir=runtime, expected_source_hashes=hashes
    )
    assert resumed.state == "ready"
    assert len(resumed.already_migrated) == 1
    assert len(resumed.migrated) == 1
    after = preview_experiment_migration(vault_root=vault, runtime_dir=runtime)
    assert all(item.state == "already-migrated" for item in after.candidates)
    migrated = ExperimentArtifactService(vault_root=vault, runtime_dir=runtime).load(
        after.candidates[0].target_path or ""
    )
    assert "Human legacy observations stay here." in migrated.human_body
    assert migrated.metadata.origins[0].relation == "migrated-from"

    third = vault / "tracking" / "walk-c.md"
    third.write_text(legacy("Walk C", "2026-07-18"))
    changed_preview = preview_experiment_migration(vault_root=vault, runtime_dir=runtime)
    candidate = next(
        item for item in changed_preview.candidates if item.source.path.endswith("walk-c.md")
    )
    third.write_text(third.read_text() + "\nChanged after preview.\n")
    result = apply_experiment_migration(
        vault_root=vault,
        runtime_dir=runtime,
        expected_source_hashes={candidate.source.path: candidate.source.content_hash},
    )
    assert result.state == "conflict"
    assert any("changed" in diagnostic.casefold() for diagnostic in result.conflicts[0].diagnostics)


def test_privacy_is_default_deny_redacted_bounded_and_inspectable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    service = ExperimentArtifactService(vault_root=vault, runtime_dir=runtime)
    artifact = service.create(
        title="Walk",
        description="",
        category="focus",
        protocol=protocol(),
        origins=(SourceReference("diary/private-day.md", "context"),),
        now=NOW,
    )
    (vault / "diary").mkdir(parents=True)
    (vault / "diary" / "private-day.md").write_text("SecretName slept well. " + "x" * 200)
    denied = preview_experiment_context(
        vault_root=vault,
        runtime_dir=runtime,
        experiment_path=artifact.path,
        selected_paths=("diary/private-day.md",),
        redact_terms=("SecretName",),
        max_item_bytes=120,
        max_total_bytes=180,
    )
    assert denied.local_analysis_only is True
    assert denied.provider_payload_paths == (artifact.path,)
    assert denied.omissions[0].reason == "protected-default-deny"
    assert "not followed automatically" in denied.disclosure
    allowed = preview_experiment_context(
        vault_root=vault,
        runtime_dir=runtime,
        experiment_path=artifact.path,
        selected_paths=("diary/private-day.md",),
        allowed_sensitive_roots=("diary",),
        redact_terms=("SecretName",),
        max_item_bytes=120,
        max_total_bytes=240,
    )
    diary_item = next(item for item in allowed.items if item.path.startswith("diary/"))
    assert "SecretName" not in diary_item.excerpt
    assert "[REDACTED-1]" in diary_item.excerpt
    assert diary_item.redactions[0]["occurrences"] == 1
    assert allowed.total_bytes <= 240
    assert allowed.truncated is True


def test_recovery_reports_moves_duplicates_missing_sources_orphans_and_interruptions(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    service = ExperimentArtifactService(vault_root=vault, runtime_dir=runtime)
    artifact = service.create(
        title="Walk",
        description="",
        category="focus",
        protocol=protocol(),
        origins=(SourceReference("captures/missing.md", "origin"),),
        now=NOW,
    )
    initial = rebuild_experiment_index(vault_root=vault, runtime_dir=runtime)
    assert len(initial.entries) == 1
    moved_path = "experiments/2026/moved-walk.md"
    (vault / moved_path).parent.mkdir(parents=True, exist_ok=True)
    (vault / artifact.path).rename(vault / moved_path)
    (vault / "observations").mkdir(parents=True)
    (vault / "observations" / "orphan.md").write_text(
        "---\ntype: experiment-observation\nexperiment_id: exp-missing\n---\n"
    )
    report = audit_experiment_recovery(vault_root=vault, runtime_dir=runtime)
    codes = {item["code"] for item in report.diagnostics}
    assert {"moved_artifact", "missing_linked_source", "orphaned_observation"} <= codes

    duplicate = vault / "experiments" / "2026" / "duplicate.md"
    duplicate.write_text((vault / moved_path).read_text())
    duplicate_report = audit_experiment_recovery(vault_root=vault, runtime_dir=runtime)
    assert any(item["code"] == "duplicate_identity" for item in duplicate_report.diagnostics)
    duplicate.unlink()
    interrupted = audit_experiment_recovery(
        vault_root=vault, runtime_dir=runtime, rebuild=True, interrupt_after=1
    )
    assert interrupted.state == "interrupted"
    assert interrupted.index.checkpoint_path is not None
    recovered = audit_experiment_recovery(vault_root=vault, runtime_dir=runtime, rebuild=True)
    assert recovered.index.state == "ready"


def test_large_history_rebuild_is_deterministic_and_disposable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    service = ExperimentArtifactService(vault_root=vault, runtime_dir=runtime)
    for offset in range(60):
        service.create(
            title=f"Experiment {offset}",
            description="",
            category="scale",
            protocol=protocol(),
            now=NOW + timedelta(seconds=offset),
        )
    first = rebuild_experiment_index(vault_root=vault, runtime_dir=runtime, batch_size=7)
    assert len(first.entries) == 60
    index_path = runtime / "experiments" / "index.json"
    index_path.unlink()
    rebuilt = rebuild_experiment_index(vault_root=vault, runtime_dir=runtime, batch_size=11)
    assert [item.experiment_id for item in rebuilt.entries] == [
        item.experiment_id for item in first.entries
    ]
    assert not (runtime / "experiments" / "rebuild-checkpoint.json").exists()


def test_malformed_legacy_source_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    (vault / "tracking").mkdir(parents=True)
    (vault / "tracking" / "bad.md").write_text(
        "---\ntype: personal-experiment-v0\ntitle: Bad\n---\n"
    )
    preview = preview_experiment_migration(vault_root=vault, runtime_dir=runtime)
    assert preview.candidates[0].state == "malformed"
    result = apply_experiment_migration(
        vault_root=vault,
        runtime_dir=runtime,
        expected_source_hashes={preview.candidates[0].source.path: "wrong"},
    )
    assert result.state == "conflict"
    assert result.migrated == ()
