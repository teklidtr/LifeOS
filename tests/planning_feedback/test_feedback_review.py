from __future__ import annotations

from datetime import date
from pathlib import Path

from lifeos.feedback import build_feedback_review_summary
from lifeos.reviews import build_review_workflow


def _write_plan(vault: Path) -> None:
    (vault / "plans").mkdir(parents=True)
    events = "\n".join(
        f"  - schema_version: 1\n    event_id: e{index}\n    task_id: t\n    outcome: done\n    date: 2026-07-{index + 9:02d}\n    actual_minutes: 60"
        for index in range(1, 6)
    )
    (vault / "plans" / "p.md").write_text(
        "---\n"
        "id: plan-p\n"
        "type: plan\n"
        "title: Plan\n"
        "status: active\n"
        "goal: goal-g\n"
        "tasks:\n"
        "  - task_id: t\n"
        "    title: Write note\n"
        "    status: todo\n"
        "    duration: 30\n"
        "    energy: medium\n"
        "    motivation: medium\n"
        "    mode: writing\n"
        "    blocked_by: []\n"
        "execution_history:\n"
        f"{events}\n"
        "---\n# Plan\n",
        encoding="utf-8",
    )


def test_weekly_summary_surfaces_duration_evidence_without_mutating_plan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    _write_plan(vault)
    before = (vault / "plans" / "p.md").read_bytes()

    suggestions = build_feedback_review_summary(vault_root=vault, as_of=date(2026, 7, 16))

    assert any(item.kind == "systematic_duration_error" for item in suggestions)
    suggestion = next(item for item in suggestions if item.kind == "systematic_duration_error")
    assert suggestion.proposed_action == "update_task_estimate"
    assert len(suggestion.evidence_event_ids) >= 3
    assert (vault / "plans" / "p.md").read_bytes() == before

    workflow = build_review_workflow(
        vault_root=vault,
        runtime_dir=runtime,
        kind="weekly",
        day=date(2026, 7, 16),
    )
    section = next(item for item in workflow.sections if item.section_id == "adaptive-feedback")
    assert section.state == "ready"
    assert "Adaptive planning feedback" in workflow.facts_markdown
