from datetime import date
from pathlib import Path

import pytest

from lifeos.daily import (
    CheckInRequest,
    DailyInteractionError,
    DailyInteractionService,
    QuickCaptureRequest,
    ReviewNoteRequest,
    TaskOutcomeRequest,
    content_hash,
)


def service(tmp_path: Path) -> DailyInteractionService:
    vault = tmp_path / "vault"
    vault.mkdir()
    return DailyInteractionService(vault_root=vault, runtime_dir=tmp_path / "runtime")


def test_capture_is_idempotent(tmp_path: Path) -> None:
    app = service(tmp_path)
    request = QuickCaptureRequest("capture-1", "thought", "A useful thought", "Body")
    first = app.quick_capture(request)
    second = app.quick_capture(request)
    assert first == second
    assert (app.vault_root / first.reference.path).read_text().count("Body") == 1


def test_idempotency_key_cannot_be_reused(tmp_path: Path) -> None:
    app = service(tmp_path)
    app.quick_capture(QuickCaptureRequest("capture-1", "thought", "First"))
    with pytest.raises(DailyInteractionError, match="different action") as caught:
        app.quick_capture(QuickCaptureRequest("capture-1", "thought", "Second"))
    assert caught.value.code == "idempotency_conflict"


def test_checkin_rejects_stale_update_and_preserves_edit(tmp_path: Path) -> None:
    app = service(tmp_path)
    created = app.update_checkin(
        CheckInRequest("morning-1", date(2026, 7, 16), "morning", {"energy": 6})
    )
    path = app.vault_root / created.reference.path
    path.write_text(path.read_text() + "Manual edit\n")
    with pytest.raises(DailyInteractionError) as caught:
        app.update_checkin(
            CheckInRequest(
                "evening-1",
                date(2026, 7, 16),
                "evening",
                {"energy": 4},
                expected_hash=created.reference.content_hash,
            )
        )
    assert caught.value.code == "stale_write"
    assert "Manual edit" in path.read_text()


def test_task_outcome_updates_only_targeted_structure(tmp_path: Path) -> None:
    app = service(tmp_path)
    plan = app.vault_root / "plans" / "p.md"
    plan.parent.mkdir()
    plan.write_text(
        """---\nid: p\ntype: plan\ntitle: P\nstatus: active\ntasks:\n  - task_id: t1\n    title: Work\n    status: todo\n    duration: 20\n    energy: low\n    motivation: low\n    mode: writing\n---\n\nHuman prose.\n"""
    )
    before = content_hash(plan.read_text())
    result = app.record_task_outcome(
        TaskOutcomeRequest(
            "outcome-1", "plans/p.md", "t1", "done", date(2026, 7, 16), before, actual_minutes=19
        )
    )
    assert result.data["outcome"] == "done"
    text = plan.read_text()
    assert "Human prose." in text
    assert "outcome: done" in text
    assert "status: done" in text


def test_review_update_preserves_reflection(tmp_path: Path) -> None:
    app = service(tmp_path)
    created = app.create_review_note(
        ReviewNoteRequest("review-1", "weekly", date(2026, 7, 16), "- fact")
    )
    path = app.vault_root / created.reference.path
    path.write_text(path.read_text() + "My reflection\n")
    current = content_hash(path.read_text())
    app.create_review_note(
        ReviewNoteRequest("review-2", "weekly", date(2026, 7, 16), "- new fact", current)
    )
    text = path.read_text()
    assert "- new fact" in text
    assert "My reflection" in text


def test_invalid_path_fails_closed(tmp_path: Path) -> None:
    app = service(tmp_path)
    with pytest.raises(DailyInteractionError) as caught:
        app.quick_capture(
            QuickCaptureRequest("capture-1", "thought", "Bad", target_path="../escape.md")
        )
    assert caught.value.code == "invalid_path"


def test_capture_task_project_flashcard_journal_and_metric(tmp_path: Path) -> None:
    app = service(tmp_path)
    plan = app.vault_root / "plans" / "existing.md"
    plan.parent.mkdir()
    plan.write_text(
        "---\nid: existing\ntype: plan\ntitle: Existing\nstatus: active\ntasks: []\n---\n\nKeep me.\n"
    )
    plan_hash = content_hash(plan.read_text())
    task = app.quick_capture(
        QuickCaptureRequest(
            "task-1",
            "task",
            "Do it",
            plan_path="plans/existing.md",
            expected_hash=plan_hash,
            task={"task_id": "do-it", "duration": 15},
        )
    )
    assert task.reference.block == "do-it"
    assert "Keep me." in plan.read_text()
    project = app.quick_capture(
        QuickCaptureRequest(
            "project-1", "project", "Learn cells", metadata={"desired_outcome": "Explain cells"}
        )
    )
    assert project.reference.path.startswith("plans/")
    card = app.quick_capture(
        QuickCaptureRequest(
            "card-1",
            "flashcard",
            "Membrane?",
            metadata={"question": "Membrane?", "answer": "Bilayer", "topic": "Biology"},
        )
    )
    assert "answer: Bilayer" in (app.vault_root / card.reference.path).read_text()
    journal = app.quick_capture(
        QuickCaptureRequest(
            "journal-1", "journal", "Observation", "Felt focused", metadata={"day": "2026-07-16"}
        )
    )
    assert journal.reference.path == "journal/2026-07-16.md"
    current = content_hash((app.vault_root / journal.reference.path).read_text())
    metric = app.quick_capture(
        QuickCaptureRequest(
            "metric-1",
            "metric",
            "Energy",
            metadata={"day": "2026-07-16", "metric": "energy", "value": 7},
            expected_hash=current,
        )
    )
    assert metric.data["metric"] == "energy"


def test_task_capture_stale_plan_is_rejected(tmp_path: Path) -> None:
    app = service(tmp_path)
    plan = app.vault_root / "plans" / "p.md"
    plan.parent.mkdir()
    plan.write_text("---\nid: p\ntype: plan\ntitle: P\nstatus: active\ntasks: []\n---\n")
    stale = content_hash(plan.read_text())
    plan.write_text(plan.read_text() + "Manual\n")
    with pytest.raises(DailyInteractionError) as caught:
        app.quick_capture(
            QuickCaptureRequest(
                "task-1",
                "task",
                "Do",
                plan_path="plans/p.md",
                expected_hash=stale,
                task={"task_id": "do", "duration": 5},
            )
        )
    assert caught.value.code == "stale_write"
