from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import lifeos.experiments.history as experiment_history
import lifeos.experiments.recovery as experiment_recovery
from lifeos.experiments import (
    ExperimentArtifactService,
    ExperimentPhase,
    ExperimentProtocol,
    MeasureDefinition,
)

NOW = datetime(2026, 7, 16, 9, tzinfo=timezone.utc)


def _protocol() -> ExperimentProtocol:
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


def test_interrupted_experiment_recovery_reads_only_the_bounded_source_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / ".lifeos"
    experiments = ExperimentArtifactService(vault_root=tmp_path, runtime_dir=runtime)
    for index in range(3):
        experiments.create(
            title=f"Experiment {index}",
            description="",
            category="study",
            protocol=_protocol(),
            now=NOW + timedelta(seconds=index),
        )

    reads: list[str] = []
    real_read = experiment_history.read_vault_markdown

    def recording_read(vault_root: Path, relative_path: str):
        reads.append(relative_path)
        return real_read(vault_root, relative_path)

    def unexpected_full_audit(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("full experiment audit ran after an interrupted rebuild")

    monkeypatch.setattr(experiment_history, "read_vault_markdown", recording_read)
    monkeypatch.setattr(experiment_recovery, "iter_vault_markdown", unexpected_full_audit)

    report = experiment_recovery.audit_experiment_recovery(
        vault_root=tmp_path,
        runtime_dir=runtime,
        rebuild=True,
        interrupt_after=1,
    )

    assert report.state == "interrupted"
    assert report.index.state == "interrupted"
    assert len(reads) == 1
    assert reads[0].startswith("experiments/")
    assert report.diagnostics == ()
