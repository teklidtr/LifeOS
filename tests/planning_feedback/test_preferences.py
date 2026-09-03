from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.daily.errors import DailyInteractionError
from lifeos.feedback import (
    FeedbackControlService,
    OutcomeCorrection,
    PreferencesUpdate,
    build_evidence_dataset,
)
from lifeos.daily.service import content_hash
from lifeos.markdown.parser import parse_markdown_note


def body_bytes(path: Path) -> bytes:
    raw = path.read_bytes().decode("utf-8")
    return parse_markdown_note(path, content=raw).body.encode("utf-8")


def test_mode_disable_exclude_dismiss_and_reset_are_canonical(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    service = FeedbackControlService(
        vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user"
    )
    initial = service.load()
    updated = service.update(
        PreferencesUpdate(
            "set-1",
            initial.content_hash,
            mode="shadow",
            disabled_dimensions=("energy",),
            exclude_event_id="e1",
            dismiss_diagnosis_id="d1",
            dismiss_fingerprint="f1",
            reset_before=date(2026, 7, 1),
            reset_reason="fresh start",
        )
    )
    assert updated.mode == "shadow"
    assert updated.disabled_dimensions == ("energy",)
    assert updated.excluded_event_ids == ("e1",)
    assert updated.dismissed_fingerprints() == ("f1",)
    assert updated.reset_before == date(2026, 7, 1)
    assert (vault / "system" / "adaptive-planning.yml").exists()


def test_stale_write_and_idempotency_conflict_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    service = FeedbackControlService(
        vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user"
    )
    first = service.update(PreferencesUpdate("same", None, mode="shadow"))
    assert service.update(PreferencesUpdate("same", None, mode="shadow")) == first
    with pytest.raises(DailyInteractionError, match="idempotency"):
        service.update(PreferencesUpdate("same", first.content_hash, mode="active"))
    with pytest.raises(DailyInteractionError, match="changed"):
        service.update(PreferencesUpdate("new", None, mode="active"))


def test_outcome_correction_preserves_source_and_builds_lineage(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "plans").mkdir(parents=True)
    path = vault / "plans" / "p.md"
    original_body = b"\r\n\r\nHuman correction notes with hard break.  \r\n\tTail"
    path.write_bytes(
        b"---\nid: p\ntype: plan\ntasks:\n  - task_id: t\n    title: T\n    status: todo\n"
        b"    duration: 30\n    energy: medium\n    motivation: medium\n    mode: writing\n"
        b"execution_history:\n  - event_id: old\n    task_id: t\n    outcome: skipped\n"
        b"    date: 2026-07-10\n    actor: user\n---\n" + original_body
    )
    service = FeedbackControlService(
        vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user"
    )
    result = service.correct_outcome(
        OutcomeCorrection(
            "correct-1",
            "plans/p.md",
            "old",
            "done",
            date(2026, 7, 10),
            content_hash(path.read_bytes()),
            actual_minutes=25,
            completion_fraction=1.0,
            reason="forgot to record",
        )
    )
    assert result["corrects_event_id"] == "old"
    assert body_bytes(path) == original_body
    dataset = build_evidence_dataset(vault)
    assert [item.event_id for item in dataset.observations] == ["correct-1"]
    assert dataset.observations[0].correction_lineage == ("old",)


def test_exclusion_preserves_history_and_reset_removes_only_derived(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    (runtime / "feedback").mkdir(parents=True)
    (runtime / "feedback" / "derived.json").write_text("{}")
    service = FeedbackControlService(vault_root=vault, runtime_dir=runtime, actor_id="user")
    service.update(PreferencesUpdate("exclude", None, exclude_event_id="e1"))
    removed = service.reset_derived()
    assert "feedback/derived.json" in removed
    assert (vault / "system" / "adaptive-planning.yml").exists()
