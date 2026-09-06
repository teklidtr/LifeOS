from __future__ import annotations

from datetime import date
from pathlib import Path

from lifeos.feedback import build_evidence_dataset, rebuild_evidence_dataset, serialize_dataset


def write_plan(vault: Path, history: str, *, tasks: str = "") -> None:
    (vault / "plans").mkdir(parents=True, exist_ok=True)
    if not tasks:
        tasks = """\n  - task_id: write-note\n    title: Write note\n    status: todo\n    duration: 30\n    energy: medium\n    motivation: low\n    mode: writing\n    task_shape: synthesis\n    blocked_by: []"""
    (vault / "plans" / "p.md").write_text(
        f"""---\nid: plan-p\ntype: plan\ngoal: goal-learn\ntasks:{tasks}\nexecution_history:\n{history}\n---\n# Plan\n""",
        encoding="utf-8",
    )


def test_empty_and_single_complete_outcome(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_plan(vault, "  []")
    assert build_evidence_dataset(vault, as_of=date(2026, 7, 16)).observations == ()
    write_plan(
        vault,
        """  - event_id: e1\n    task_id: write-note\n    outcome: done\n    date: 2026-07-15\n    actual_minutes: 42\n    energy_before: medium\n    motivation_before: low""",
    )
    dataset = build_evidence_dataset(vault, as_of=date(2026, 7, 16))
    observation = dataset.observations[0]
    assert observation.task_shape == "synthesis"
    assert observation.planned_minutes == 30
    assert observation.actual_minutes == 42
    assert observation.completion_fraction == 1.0


def test_all_outcomes_and_missing_values_remain_distinct(tmp_path: Path) -> None:
    history = "\n".join(
        f"  - event_id: e{i}\n    task_id: write-note\n    outcome: {outcome}\n    date: 2026-07-{i + 1:02d}"
        for i, outcome in enumerate(("partial", "skipped", "deferred", "cancelled", "unaccounted"))
    )
    vault = tmp_path / "vault"
    write_plan(vault, history)
    observations = build_evidence_dataset(vault).observations
    assert [item.outcome for item in observations] == [
        "partial",
        "skipped",
        "deferred",
        "cancelled",
        "unaccounted",
    ]
    assert observations[0].actual_minutes is None
    assert observations[-1].completion_fraction is None


def test_corrections_retractions_and_lineage(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_plan(
        vault,
        """  - event_id: e1\n    task_id: write-note\n    outcome: skipped\n    date: 2026-07-10\n  - event_id: e2\n    task_id: write-note\n    outcome: done\n    date: 2026-07-10\n    actual_minutes: 25\n    corrects_event_id: e1\n  - event_id: e3\n    task_id: write-note\n    outcome: cancelled\n    date: 2026-07-11\n  - event_id: e4\n    task_id: write-note\n    outcome: cancelled\n    date: 2026-07-12\n    retracts_event_id: e3""",
    )
    dataset = build_evidence_dataset(vault)
    assert [item.event_id for item in dataset.observations] == ["e2"]
    assert dataset.observations[0].correction_lineage == ("e1",)
    assert dataset.corrected_event_count == 1
    assert dataset.retracted_event_count == 1


def test_duplicate_conflict_invalid_chronology_and_unsupported_schema_are_diagnostics(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    write_plan(
        vault,
        """  - event_id: duplicate\n    task_id: write-note\n    outcome: done\n    date: 2026-07-10\n  - event_id: duplicate\n    task_id: write-note\n    outcome: done\n    date: 2026-07-11\n  - event_id: bad-time\n    task_id: write-note\n    outcome: done\n    date: 2026-07-12\n    started_at: 2026-07-12T11:00:00+03:00\n    ended_at: 2026-07-12T10:00:00+03:00\n  - event_id: future\n    schema_version: 9\n    task_id: write-note\n    outcome: done\n    date: 2026-07-13""",
    )
    dataset = build_evidence_dataset(vault)
    codes = {item.code for item in dataset.diagnostics}
    assert {"duplicate_event_id", "invalid_chronology", "unsupported_event_schema"} <= codes
    assert dataset.observations == ()


def test_orphaned_task_is_retained_with_warning(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_plan(
        vault,
        """  - event_id: old\n    task_id: removed-task\n    task_title: Old title\n    mode: reading\n    planned_minutes: 20\n    outcome: done\n    date: 2026-07-10\n    actual_minutes: 18""",
    )
    dataset = build_evidence_dataset(vault)
    assert dataset.observations[0].task_id == "removed-task"
    assert any(
        item.code == "orphaned_task_reference" and item.severity == "warning"
        for item in dataset.diagnostics
    )


def test_rebuild_is_deterministic_and_reuses_equivalent_cache(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    write_plan(
        vault,
        """  - event_id: e1\n    task_id: write-note\n    outcome: done\n    date: 2026-07-10\n    actual_minutes: 35""",
    )
    first, first_status = rebuild_evidence_dataset(vault, runtime, as_of=date(2026, 7, 16))
    second, second_status = rebuild_evidence_dataset(vault, runtime, as_of=date(2026, 7, 16))
    assert serialize_dataset(first) == serialize_dataset(second)
    assert first_status.reused is False
    assert second_status.reused is True
