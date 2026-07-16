from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.attention import evaluate_attention
from lifeos.daily import DailyInteractionService, TaskOutcomeRequest, content_hash
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.progress import ReviewProgressService
from lifeos.reviews.weekly_review import complete_weekly_review, open_weekly_review

SUNDAY = datetime(2026, 7, 19, 18, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")


def setup(tmp_path: Path):
    vault = tmp_path / "vault"; vault.mkdir(); runtime = tmp_path / "runtime"
    write(vault / "plans" / "plan.md", "---\nid: p\ntype: plan\ntitle: Plan\nstatus: active\ntasks:\n  - task_id: t1\n    title: Do it\n    status: todo\n---\n")
    write(vault / "experiments" / "sleep.md", "---\ntype: experiment\ntitle: Sleep experiment\nstatus: active\nrequired_metrics: [sleep_hours]\n---\n")
    return vault, runtime, ReviewArtifactService(vault_root=vault, runtime_dir=runtime, actor_id="me")


def test_weekly_review_uses_iso_identity_and_bounded_sections(tmp_path: Path) -> None:
    _, runtime, service = setup(tmp_path)
    state = open_weekly_review(service=service, runtime_dir=runtime, day=date(2026, 1, 1), timezone="UTC", now=datetime(2026, 1, 4, 18, tzinfo=timezone.utc), idempotency_key="open")
    assert state.artifact.path == "reviews/weekly/2026-W01.md"
    assert state.artifact.metadata.period_start.isoformat() == "2025-12-29"
    ids = {section.section_id for section in state.snapshot.sections}
    assert {"goal-plan-reviews", "adaptive-feedback", "weekly-evidence", "experiments", "system-health"} <= ids
    assert "system-health" not in state.required_sections


def test_weekly_evidence_summarizes_outcomes_and_active_experiments(tmp_path: Path) -> None:
    vault, runtime, service = setup(tmp_path)
    plan = vault / "plans" / "plan.md"
    DailyInteractionService(vault_root=vault, runtime_dir=runtime).record_task_outcome(TaskOutcomeRequest("outcome", "plans/plan.md", "t1", "done", date(2026, 7, 16), content_hash(plan.read_text())))
    state = open_weekly_review(service=service, runtime_dir=runtime, day=date(2026, 7, 16), timezone="UTC", now=SUNDAY, idempotency_key="open")
    execution = next(section for section in state.snapshot.sections if section.section_id == "weekly-evidence")
    assert "done: 1" in execution.items[0].detail
    experiments = next(section for section in state.snapshot.sections if section.section_id == "experiments")
    assert experiments.items[0].title == "Sleep experiment"
    assert "sleep_hours" in experiments.items[0].detail


def test_weekly_completion_requires_only_non_optional_sections(tmp_path: Path) -> None:
    _, runtime, service = setup(tmp_path)
    state = open_weekly_review(service=service, runtime_dir=runtime, day=date(2026, 7, 16), timezone="UTC", now=SUNDAY, idempotency_key="open")
    progress = ReviewProgressService(service); artifact = state.artifact
    for section_id in state.required_sections:
        artifact = progress.update_section(review_id=artifact.metadata.review_id, phase_id="weekly", section_id=section_id, action="complete", expected_hash=artifact.content_hash, idempotency_key=f"section-{section_id}", now=SUNDAY)
    state = open_weekly_review(service=service, runtime_dir=runtime, day=date(2026, 7, 16), timezone="UTC", now=SUNDAY, idempotency_key="resume", refresh=False)
    completed = complete_weekly_review(service=service, state=state, now=SUNDAY, idempotency_key="complete")
    assert completed.artifact.metadata.status == "completed"
    assert completed.due.state == "completed"


def test_weekly_attention_is_opt_in_until_artifact_exists(tmp_path: Path) -> None:
    vault, runtime, service = setup(tmp_path)
    before = evaluate_attention(vault_root=vault, runtime_dir=runtime, as_of=SUNDAY)
    assert not any(item.kind == "weekly_review" for item in before.items)
    open_weekly_review(service=service, runtime_dir=runtime, day=date(2026, 7, 16), timezone="UTC", now=datetime(2026, 7, 16, 12, tzinfo=timezone.utc), idempotency_key="open")
    after = evaluate_attention(vault_root=vault, runtime_dir=runtime, as_of=SUNDAY)
    assert any(item.kind == "weekly_review" for item in after.items)
