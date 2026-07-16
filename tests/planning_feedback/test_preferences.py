from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifeos.daily.errors import DailyInteractionError
from lifeos.feedback import FeedbackControlService, OutcomeCorrection, PreferencesUpdate, build_evidence_dataset
from lifeos.daily.service import content_hash


def test_mode_disable_exclude_dismiss_and_reset_are_canonical(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = FeedbackControlService(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user")
    initial = service.load()
    updated = service.update(PreferencesUpdate("set-1", initial.content_hash, mode="shadow", disabled_dimensions=("energy",), exclude_event_id="e1", dismiss_diagnosis_id="d1", dismiss_fingerprint="f1", reset_before=date(2026, 7, 1), reset_reason="fresh start"))
    assert updated.mode == "shadow"
    assert updated.disabled_dimensions == ("energy",)
    assert updated.excluded_event_ids == ("e1",)
    assert updated.dismissed_fingerprints() == ("f1",)
    assert updated.reset_before == date(2026, 7, 1)
    assert (vault / "system" / "adaptive-planning.yml").exists()


def test_stale_write_and_idempotency_conflict_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    service = FeedbackControlService(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user")
    first = service.update(PreferencesUpdate("same", None, mode="shadow"))
    assert service.update(PreferencesUpdate("same", None, mode="shadow")) == first
    with pytest.raises(DailyInteractionError, match="idempotency"):
        service.update(PreferencesUpdate("same", first.content_hash, mode="active"))
    with pytest.raises(DailyInteractionError, match="changed"):
        service.update(PreferencesUpdate("new", None, mode="active"))


def test_outcome_correction_preserves_source_and_builds_lineage(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; (vault / "plans").mkdir(parents=True)
    path = vault / "plans" / "p.md"
    path.write_text("""---\nid: p\ntype: plan\ntasks:\n  - task_id: t\n    title: T\n    status: todo\n    duration: 30\n    energy: medium\n    motivation: medium\n    mode: writing\nexecution_history:\n  - event_id: old\n    task_id: t\n    outcome: skipped\n    date: 2026-07-10\n    actor: user\n---\n""", encoding="utf-8")
    service = FeedbackControlService(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="user")
    result = service.correct_outcome(OutcomeCorrection("correct-1", "plans/p.md", "old", "done", date(2026, 7, 10), content_hash(path.read_text()), actual_minutes=25, completion_fraction=1.0, reason="forgot to record"))
    assert result["corrects_event_id"] == "old"
    dataset = build_evidence_dataset(vault)
    assert [item.event_id for item in dataset.observations] == ["correct-1"]
    assert dataset.observations[0].correction_lineage == ("old",)


def test_exclusion_preserves_history_and_reset_removes_only_derived(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; vault.mkdir()
    runtime = tmp_path / "runtime"; (runtime / "feedback").mkdir(parents=True)
    (runtime / "feedback" / "derived.json").write_text("{}")
    service = FeedbackControlService(vault_root=vault, runtime_dir=runtime, actor_id="user")
    service.update(PreferencesUpdate("exclude", None, exclude_event_id="e1"))
    removed = service.reset_derived()
    assert "feedback/derived.json" in removed
    assert (vault / "system" / "adaptive-planning.yml").exists()
