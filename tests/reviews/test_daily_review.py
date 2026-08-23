from datetime import date, datetime, timezone
from pathlib import Path

from lifeos.attention import evaluate_attention
from lifeos.daily import DailyInteractionService, CheckInRequest, TaskOutcomeRequest, content_hash
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.daily_review import complete_daily_phase, open_daily_review
from lifeos.reviews.progress import ReviewProgressService

MORNING = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)
EVENING = datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def setup(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write(
        vault / "plans" / "plan.md",
        "---\nid: p\ntype: plan\ntitle: Plan\nstatus: active\ntasks:\n  - task_id: t1\n    title: Do it\n    status: todo\n    planned_for: 2026-07-16\n---\n",
    )
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime, actor_id="me")
    return vault, runtime, service


def test_one_daily_artifact_supports_morning_and_evening_entry(tmp_path: Path) -> None:
    _, runtime, service = setup(tmp_path)
    morning = open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=MORNING,
        idempotency_key="morning",
        phase="morning",
    )
    evening = open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=EVENING,
        idempotency_key="evening",
        phase="evening",
    )
    assert morning.artifact.path == evening.artifact.path == "reviews/daily/2026-07-16.md"
    assert evening.active_phase == "evening"
    assert {section.section_id for section in evening.snapshot.sections} >= {
        "plans",
        "daily-evidence",
    }
    assert evening.due.state == "due"


def test_evening_can_complete_when_morning_is_intentionally_skipped(tmp_path: Path) -> None:
    _, runtime, service = setup(tmp_path)
    state = open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=EVENING,
        idempotency_key="open",
        phase="evening",
    )
    progress = ReviewProgressService(service)
    artifact = progress.update_phase(
        review_id=state.artifact.metadata.review_id,
        phase_id="morning",
        action="skip",
        required_sections=(),
        expected_hash=state.artifact.content_hash,
        idempotency_key="skip-morning",
        now=EVENING,
    )
    for section_id in state.required_sections:
        artifact = progress.update_section(
            review_id=artifact.metadata.review_id,
            phase_id="evening",
            section_id=section_id,
            action="complete",
            expected_hash=artifact.content_hash,
            idempotency_key=f"section-{section_id}",
            now=EVENING,
        )
    state = open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=EVENING,
        idempotency_key="resume",
        phase="evening",
        refresh=False,
    )
    completed = complete_daily_phase(
        service=service,
        runtime_dir=runtime,
        state=state,
        now=EVENING,
        idempotency_key="complete-evening",
    )
    assert completed.artifact.metadata.phases[0].state == "skipped"
    assert completed.artifact.metadata.phases[1].state == "completed"


def test_daily_snapshot_links_checkins_and_explicit_outcomes(tmp_path: Path) -> None:
    vault, runtime, service = setup(tmp_path)
    daily = DailyInteractionService(vault_root=vault, runtime_dir=runtime, actor_id="me")
    daily.update_checkin(CheckInRequest("checkin", date(2026, 7, 16), "morning", {"energy": 6}))
    plan = vault / "plans" / "plan.md"
    daily.record_task_outcome(
        TaskOutcomeRequest(
            "outcome",
            "plans/plan.md",
            "t1",
            "done",
            date(2026, 7, 16),
            content_hash(plan.read_text()),
        )
    )
    state = open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=EVENING,
        idempotency_key="open",
        phase="evening",
    )
    evidence = next(
        section for section in state.snapshot.sections if section.section_id == "daily-evidence"
    )
    assert any(
        "recorded" in item.detail
        for item in evidence.items
        if item.item_id.endswith("morning-checkin")
    )
    assert any("1 explicit task outcome" in item.detail for item in evidence.items)


def test_attention_only_prompts_for_review_after_artifact_exists(tmp_path: Path) -> None:
    vault, runtime, service = setup(tmp_path)
    before = evaluate_attention(vault_root=vault, runtime_dir=runtime, as_of=EVENING)
    assert not any(item.kind == "daily_review_phase" for item in before.items)
    open_daily_review(
        service=service,
        runtime_dir=runtime,
        day=date(2026, 7, 16),
        timezone="UTC",
        now=MORNING,
        idempotency_key="open",
        phase="morning",
    )
    after = evaluate_attention(vault_root=vault, runtime_dir=runtime, as_of=EVENING)
    phases = [item.title for item in after.items if item.kind == "daily_review_phase"]
    assert phases == ["Resume evening review", "Resume morning review"] or set(phases) == {
        "Resume morning review",
        "Resume evening review",
    }
