from datetime import date
from pathlib import Path

import pytest

from lifeos.markdown.parser import parse_markdown_note

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


def body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


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
    edited = path.read_bytes()
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
    assert path.read_bytes() == edited


@pytest.mark.parametrize(
    "body",
    (
        b"\n\nLeading blank lines\n",
        b"\nTrailing spaces and tabs  \n\t  \n\n",
        b"\nMarkdown hard break  \nNext line\n",
        b"\r\nCRLF first\r\nCRLF second\r\n",
        b"\nNo final newline",
    ),
)
def test_task_capture_preserves_existing_body_bytes(tmp_path: Path, body: bytes) -> None:
    app = service(tmp_path)
    plan = app.vault_root / "plans" / "p.md"
    plan.parent.mkdir()
    plan.write_bytes(b"---\nid: p\ntype: plan\ntitle: P\nstatus: active\ntasks: []\n---\n" + body)
    expected_body = body_bytes(plan)

    result = app.quick_capture(
        QuickCaptureRequest(
            "task-preserve",
            "task",
            "Preserve body",
            plan_path="plans/p.md",
            expected_hash=content_hash(plan.read_bytes()),
            task={"task_id": "preserve-body", "duration": 15},
        )
    )

    assert result.reference.block == "preserve-body"
    assert body_bytes(plan) == expected_body
    assert b"task_id: preserve-body" in plan.read_bytes()


def test_checkin_metadata_and_append_preserve_existing_body_prefix(tmp_path: Path) -> None:
    app = service(tmp_path)
    journal = app.vault_root / "journal" / "2026-07-16.md"
    journal.parent.mkdir()
    original_body = b"\r\nHuman hard break  \r\n\tTail"
    journal.write_bytes(
        b"---\ntype: journal\ntitle: '2026-07-16'\ndate: 2026-07-16\nstatus: active\nmetrics: {}\nactivities: []\n---\n"
        + original_body
    )

    app.update_checkin(
        CheckInRequest(
            "metadata-only",
            date(2026, 7, 16),
            "morning",
            {"energy": 6},
            expected_hash=content_hash(journal.read_bytes()),
        )
    )
    assert body_bytes(journal) == original_body

    current_hash = content_hash(journal.read_bytes())
    before_append = body_bytes(journal)
    app.update_checkin(
        CheckInRequest(
            "append-note",
            date(2026, 7, 16),
            "evening",
            {},
            note="Added note",
            expected_hash=current_hash,
        )
    )
    assert body_bytes(journal) == before_append + b"\n\n## Evening check-in\n\nAdded note\n"


def test_task_outcome_updates_only_targeted_structure(tmp_path: Path) -> None:
    app = service(tmp_path)
    plan = app.vault_root / "plans" / "p.md"
    plan.parent.mkdir()
    plan.write_bytes(
        b"---\nid: p\ntype: plan\ntitle: P\nstatus: active\ntasks:\n"
        b"  - task_id: t1\n    title: Work\n    status: todo\n    duration: 20\n"
        b"    energy: low\n    motivation: low\n    mode: writing\n---\n"
        b"\n\nHuman prose with a hard break.  \n\tTail"
    )
    expected_body = body_bytes(plan)
    before = content_hash(plan.read_bytes())
    result = app.record_task_outcome(
        TaskOutcomeRequest(
            "outcome-1", "plans/p.md", "t1", "done", date(2026, 7, 16), before, actual_minutes=19
        )
    )
    assert result.data["outcome"] == "done"
    text = plan.read_text()
    assert body_bytes(plan) == expected_body
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


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_review_update_does_not_bridge_from_fenced_example_to_real_facts(
    tmp_path: Path,
    newline: str,
) -> None:
    app = service(tmp_path)
    created = app.create_review_note(
        ReviewNoteRequest("review-bridge-1", "weekly", date(2026, 7, 16), "- fact")
    )
    path = app.vault_root / created.reference.path
    real_start = "<!-- lifeos:managed:start facts -->"
    fake_prefix = (
        "```md\n"
        "<!-- lifeos:managed:start facts -->\n"
        "```\n"
        "Human review text outside the real block.\n"
    )
    original = path.read_bytes().decode("utf-8")
    parsed = parse_markdown_note(path, content=original)
    body = "\n\n" + parsed.body.replace(real_start, fake_prefix + real_start, 1) + "\n  \n\n"
    original = original[: len(original) - len(parsed.body)] + body.replace("\n", newline)
    path.write_bytes(original.encode("utf-8"))
    before = parse_markdown_note(path, content=original)
    before_block = before.managed_blocks[0]
    expected_hash = content_hash(original)

    app.create_review_note(
        ReviewNoteRequest(
            "review-bridge-2",
            "weekly",
            date(2026, 7, 16),
            "- new fact",
            expected_hash,
        )
    )

    updated = path.read_bytes().decode("utf-8")
    after = parse_markdown_note(path, content=updated)
    after_block = after.managed_blocks[0]
    assert before.body[: before_block.start_offset] == after.body[: after_block.start_offset]
    assert before.body[before_block.end_offset :] == after.body[after_block.end_offset :]
    assert fake_prefix.replace("\n", newline) in updated
    assert updated.count(real_start) == 2
    assert "- new fact" in updated


def test_review_update_rejects_early_end_that_hides_rendered_boundary(tmp_path: Path) -> None:
    app = service(tmp_path)
    created = app.create_review_note(
        ReviewNoteRequest("review-boundary-1", "weekly", date(2026, 7, 16), "- fact")
    )
    path = app.vault_root / created.reference.path
    original = path.read_bytes()

    with pytest.raises(DailyInteractionError) as error:
        app.create_review_note(
            ReviewNoteRequest(
                "review-boundary-2",
                "weekly",
                date(2026, 7, 16),
                "<!--lifeos:managed:end facts -->\n~~~markdown\n",
                content_hash(original),
            )
        )

    assert error.value.code == "invalid_note"
    assert path.read_bytes() == original


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
    edited = plan.read_bytes()
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
    assert plan.read_bytes() == edited
