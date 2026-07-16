from datetime import date
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError, DailyInteractionService, TaskOutcomeRequest, content_hash, execution_index, load_execution_records


def setup_plan(tmp_path: Path) -> tuple[DailyInteractionService, Path]:
    vault = tmp_path / "vault"; vault.mkdir()
    plan = vault / "plans" / "p.md"; plan.parent.mkdir()
    plan.write_text("""---
id: p
type: plan
title: P
status: active
tasks:
  - task_id: t
    title: Work
    status: todo
    duration: 30
    energy: medium
    motivation: low
    mode: writing
---
""")
    return DailyInteractionService(vault_root=vault, runtime_dir=tmp_path / "runtime"), plan


def test_multiple_attempts_and_rich_evidence_rebuild(tmp_path: Path) -> None:
    app, plan = setup_plan(tmp_path)
    first_hash = content_hash(plan.read_text())
    app.record_task_outcome(TaskOutcomeRequest("event-1", "plans/p.md", "t", "partial", date(2026, 7, 15), first_hash, planned_minutes=30, actual_minutes=20, energy_before="medium", energy_after="low", motivation_before="low", difficulty=8, satisfaction=5, reason="scope", note="Outlined", started_at="2026-07-15T23:50:00+03:00", ended_at="2026-07-16T00:10:00+03:00"))
    second_hash = content_hash(plan.read_text())
    app.record_task_outcome(TaskOutcomeRequest("event-2", "plans/p.md", "t", "done", date(2026, 7, 16), second_hash, actual_minutes=15))
    records = load_execution_records(app.vault_root)
    assert [record.outcome for record in records] == ["partial", "done"]
    assert records[0].actual_minutes == 20
    assert execution_index(app.vault_root)["t"] == records


def test_terminal_transition_fails_without_history_change(tmp_path: Path) -> None:
    app, plan = setup_plan(tmp_path)
    app.record_task_outcome(TaskOutcomeRequest("event-1", "plans/p.md", "t", "done", date(2026, 7, 16), content_hash(plan.read_text())))
    before = plan.read_text()
    with pytest.raises(DailyInteractionError) as caught:
        app.record_task_outcome(TaskOutcomeRequest("event-2", "plans/p.md", "t", "skipped", date(2026, 7, 17), content_hash(before)))
    assert caught.value.code == "invalid_transition"
    assert plan.read_text() == before


def test_defer_keeps_distinct_outcome_and_updates_due(tmp_path: Path) -> None:
    app, plan = setup_plan(tmp_path)
    app.record_task_outcome(TaskOutcomeRequest("event-1", "plans/p.md", "t", "deferred", date(2026, 7, 16), content_hash(plan.read_text()), deferred_until=date(2026, 7, 20)))
    assert "outcome: deferred" in plan.read_text()
    assert "due: 2026-07-20" in plan.read_text()
