from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path


from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentPhase,
    ExperimentProposalRequest,
    ExperimentProposalService,
    ExperimentProtocol,
    MeasureDefinition,
    create_observation,
    save_analysis,
)
from lifeos.experiments.reviews import daily_experiment_section, weekly_experiment_section

NOW = datetime(2026, 7, 16, 18, tzinfo=timezone.utc)


def protocol() -> ExperimentProtocol:
    return ExperimentProtocol(
        question="Does walk timing relate to focus?",
        hypothesis="morning is higher",
        rationale="test",
        intervention="morning walk",
        constants=(),
        comparison="baseline",
        baseline_requirements="2 days",
        outcome_measures=(MeasureDefinition("focus", "Focus", "rating", "primary", "daily"),),
        phases=(
            ExperimentPhase("base", "Baseline", "baseline", "2026-07-16", "2026-07-17"),
            ExperimentPhase("walk", "Walk", "intervention", "2026-07-18", "2026-07-19"),
        ),
        adherence_expectation="daily",
        confounders=(),
        risks=(),
        stop_rules=(),
        success_criteria=("higher",),
        failure_criteria=("not higher",),
        inconclusive_criteria=("missing",),
        schedule={"timezone": "UTC", "time": "18:00", "window_minutes": 60, "grace_minutes": 60},
    )


def active(tmp_path: Path):
    api = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    item = api.create(title="Walk", description="", category="study", protocol=protocol(), now=NOW)
    item = api.transition(item.path, "drafting", expected_hash=item.content_hash, now=NOW)
    item = api.transition(item.path, "baseline", expected_hash=item.content_hash, now=NOW)
    return api, item


def test_daily_and_weekly_review_sections_are_contextual_and_fingerprinted(tmp_path: Path) -> None:
    api, item = active(tmp_path)
    daily = daily_experiment_section(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        day=date(2026, 7, 16),
        generated_at=NOW,
    )
    assert daily.optional is True
    assert daily.items[0].action == "record-observation"
    old_fingerprint = daily.items[0].evidence_fingerprint
    obs = create_observation(
        item.metadata,
        measure_id="focus",
        phase_id="base",
        observed_at=NOW,
        state="measured",
        value=7,
    )
    item = api.append_observation(item.path, obs, expected_hash=item.content_hash, now=NOW)
    refreshed = daily_experiment_section(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        day=date(2026, 7, 16),
        generated_at=NOW,
    )
    assert refreshed.state == "empty" or all(
        entry.evidence_fingerprint != old_fingerprint for entry in refreshed.items
    )
    weekly = weekly_experiment_section(
        vault_root=tmp_path,
        runtime_dir=tmp_path / ".lifeos",
        range_start=date(2026, 7, 13),
        range_end=date(2026, 7, 19),
        generated_at=NOW,
    )
    assert weekly.items and "missing or skipped" in weekly.items[0].detail


def test_proposal_preview_contains_exact_patch_evidence_limitations_and_stale_target(
    tmp_path: Path,
) -> None:
    api, item = active(tmp_path)
    for index, (phase, value) in enumerate((("base", 5), ("base", 6), ("walk", 7), ("walk", 8))):
        obs = create_observation(
            item.metadata,
            measure_id="focus",
            phase_id=phase,
            observed_at=NOW + timedelta(days=index),
            state="measured",
            value=value,
        )
        item = api.append_observation(item.path, obs, expected_hash=item.content_hash, now=NOW)
    item = save_analysis(api, item, expected_hash=item.content_hash, now=NOW)
    target = tmp_path / "habits/focus.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\ntype: habit\n---\n\n# Focus\n")
    proposals = ExperimentProposalService(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="local-user"
    )
    request = ExperimentProposalRequest(
        item.path,
        "create-or-modify-habit",
        "habits/focus.md",
        "## Experiment finding\n\nTry a morning walk as an optional routine.",
        False,
        ("append finding",),
        ("do not auto-enable habit",),
    )
    preview, _, _ = proposals.preview(request, now=NOW)
    assert preview.base_hash and preview.unified_diff
    assert preview.source_experiment_hash == item.content_hash
    assert any(
        "does not establish causation" in limitation for limitation in preview.analysis_limitations
    )
    result = proposals.publish(request, now=NOW)
    assert (tmp_path / result["proposal_path"] / "patches.json").exists()
    assert target.read_text() == "---\ntype: habit\n---\n\n# Focus\n"
    target.write_text(target.read_text() + "changed\n")
    stale_preview, _, _ = proposals.preview(
        ExperimentProposalRequest(
            item.path, "add-weekly-review-insight", "habits/focus.md", "Another finding", False
        ),
        now=NOW + timedelta(seconds=1),
    )
    assert stale_preview.base_hash != preview.base_hash


def test_create_proposal_never_silently_creates_target(tmp_path: Path) -> None:
    _, item = active(tmp_path)
    service = ExperimentProposalService(
        vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", actor_id="local-user"
    )
    request = ExperimentProposalRequest(
        item.path, "create-knowledge-note", "notes/walk.md", "# Walk finding\n", True
    )
    preview, _, _ = service.preview(request, now=NOW)
    assert preview.operation == "create_file"
    assert not (tmp_path / "notes/walk.md").exists()
