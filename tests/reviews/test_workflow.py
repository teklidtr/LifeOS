from datetime import date
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError, content_hash
from lifeos.reviews import build_review_workflow, save_progress, save_review_note


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_first_review_sparse_vault_and_resume(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    workflow = build_review_workflow(
        vault_root=vault, runtime_dir=runtime, kind="weekly", day=date(2026, 1, 1)
    )
    assert workflow.range_start == date(2025, 12, 29)
    assert workflow.range_end == date(2026, 1, 4)
    progress = save_progress(
        runtime,
        review_id=workflow.review_id,
        completed_sections=("inbox",),
        current_section="plans",
    )
    resumed = build_review_workflow(
        vault_root=vault, runtime_dir=runtime, kind="weekly", day=date(2026, 1, 1)
    )
    assert resumed.progress == progress


def test_rebuild_facts_preserves_reflection_and_conflicts_safely(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    write(vault / "raw" / "idea.md", "---\ntype: raw\ntitle: Idea\nstatus: inbox\n---\n")
    workflow = build_review_workflow(
        vault_root=vault, runtime_dir=runtime, kind="weekly", day=date(2026, 7, 16)
    )
    first = save_review_note(
        vault_root=vault,
        runtime_dir=runtime,
        actor_id="me",
        workflow=workflow,
        idempotency_key="review-1",
    )
    path = vault / first["reference"]["path"]
    path.write_text(path.read_text() + "My reflection.\n")
    current = content_hash(path.read_text())
    write(vault / "raw" / "second.md", "---\ntype: raw\ntitle: Second\nstatus: inbox\n---\n")
    rebuilt = build_review_workflow(
        vault_root=vault, runtime_dir=runtime, kind="weekly", day=date(2026, 7, 16)
    )
    save_review_note(
        vault_root=vault,
        runtime_dir=runtime,
        actor_id="me",
        workflow=rebuilt,
        idempotency_key="review-2",
        expected_hash=current,
    )
    assert "My reflection." in path.read_text()
    stale = current
    path.write_text(path.read_text() + "External edit\n")
    with pytest.raises(DailyInteractionError) as caught:
        save_review_note(
            vault_root=vault,
            runtime_dir=runtime,
            actor_id="me",
            workflow=rebuilt,
            idempotency_key="review-3",
            expected_hash=stale,
        )
    assert caught.value.code == "stale_write"
