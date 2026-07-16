from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from lifeos.daily import DailyInteractionError
from lifeos.feedback import (
    AdaptivePreferences,
    FeedbackControlService,
    FeedbackObservation,
    apply_preferences,
)


def service(tmp_path: Path) -> FeedbackControlService:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    return FeedbackControlService(vault_root=vault, runtime_dir=runtime, actor_id="user")


def test_legacy_preferences_migrate_safely_to_shadow(tmp_path: Path) -> None:
    controls = service(tmp_path)
    controls.preferences_path.parent.mkdir(parents=True)
    controls.preferences_path.write_text(
        "schema_version: 0\n"
        "enabled: true\n"
        "disabled_signals: [energy]\n"
        "excluded_events: [e1]\n",
        encoding="utf-8",
    )
    original = controls.preferences_path.read_bytes()

    dry = controls.migrate(dry_run=True)
    assert dry.state == "migratable"
    assert dry.mode == "shadow"
    assert controls.preferences_path.read_bytes() == original

    migrated = controls.migrate(dry_run=False)
    assert migrated.state == "migrated"
    loaded = controls.load()
    assert loaded.mode == "shadow"
    assert loaded.disabled_dimensions == ("energy",)
    assert loaded.excluded_event_ids == ("e1",)


def test_incompatible_preference_schema_is_rejected_without_rewrite(tmp_path: Path) -> None:
    controls = service(tmp_path)
    controls.preferences_path.parent.mkdir(parents=True)
    controls.preferences_path.write_text("schema_version: 99\n", encoding="utf-8")
    before = controls.preferences_path.read_bytes()

    with pytest.raises(DailyInteractionError) as captured:
        controls.migrate(dry_run=False)

    assert captured.value.code == "unsupported_feedback_preferences"
    assert controls.preferences_path.read_bytes() == before


def test_exclusion_and_reset_mark_derived_evidence_only() -> None:
    base = FeedbackObservation(
        1,
        "obs-e1",
        "e1",
        "plans/p.md",
        "hash",
        0,
        date(2026, 7, 1),
        "plan",
        "goal",
        "task",
        "Task",
        "shape",
        "writing",
        "medium",
        "medium",
        False,
        "done",
        1.0,
        30,
        30,
        "medium",
        "medium",
        "medium",
        None,
        None,
        None,
        (),
    )
    newer = replace(base, observation_id="obs-e2", event_id="e2", day=date(2026, 7, 10))
    preferences = AdaptivePreferences(
        mode="active",
        excluded_event_ids=("e2",),
        reset_before=date(2026, 7, 5),
    )

    applied = apply_preferences((base, newer), preferences)

    assert applied[0].excluded is True
    assert applied[1].excluded is True
    assert base.excluded is False
    assert newer.excluded is False


def test_existing_legacy_file_requires_explicit_migration(tmp_path: Path) -> None:
    controls = service(tmp_path)
    controls.preferences_path.parent.mkdir(parents=True)
    controls.preferences_path.write_text("enabled: true\n", encoding="utf-8")

    with pytest.raises(DailyInteractionError) as captured:
        controls.load()

    assert captured.value.code == "unsupported_feedback_preferences"
    assert controls.migrate(dry_run=True).state == "migratable"


@pytest.mark.parametrize("schema_version", [True, 1.0, "1"])
def test_preference_schema_requires_an_integer(
    tmp_path: Path, schema_version: object
) -> None:
    controls = service(tmp_path)
    controls.preferences_path.parent.mkdir(parents=True)
    controls.preferences_path.write_text(
        yaml.safe_dump({"schema_version": schema_version}),
        encoding="utf-8",
    )

    with pytest.raises(DailyInteractionError) as captured:
        controls.load()

    assert captured.value.code == "unsupported_feedback_preferences"


def test_preferences_reject_unknown_fields_and_symlinks(tmp_path: Path) -> None:
    controls = service(tmp_path)
    controls.preferences_path.parent.mkdir(parents=True)
    controls.preferences_path.write_text(
        "schema_version: 1\nmode: off\nmodee: active\n", encoding="utf-8"
    )
    with pytest.raises(DailyInteractionError) as captured:
        controls.load()
    assert captured.value.code == "invalid_feedback_preferences"

    outside = tmp_path / "outside.yml"
    outside.write_text("schema_version: 1\nmode: active\n", encoding="utf-8")
    controls.preferences_path.unlink()
    try:
        controls.preferences_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(DailyInteractionError) as captured:
        controls.load()
    assert captured.value.code == "unsafe_path"
    assert outside.read_text(encoding="utf-8") == "schema_version: 1\nmode: active\n"
