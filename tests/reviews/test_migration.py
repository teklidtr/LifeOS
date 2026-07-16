from datetime import datetime
from pathlib import Path

from lifeos.reviews import (
    ReviewArtifactService,
    apply_review_migration,
    preview_review_migration,
    rebuild_review_state,
)

NOW = datetime.fromisoformat("2026-07-16T12:00:00+03:00")


def legacy(kind: str, day: str, reflection: str) -> str:
    return f"""---
type: review
review_kind: {kind}
date: {day}
status: active
---

# {kind.title()} review

<!-- lifeos:managed:start facts -->
## {kind.title()} review facts

- Managed old fact.
<!-- lifeos:managed:end facts -->

## Reflection

{reflection}
"""


def test_preview_and_apply_merge_daily_reflections_without_deleting_sources(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; reviews = vault / "reviews"; reviews.mkdir(parents=True)
    morning = reviews / "morning-2026-07-16.md"; evening = reviews / "evening-2026-07-16.md"
    morning.write_text(legacy("morning", "2026-07-16", "Protect the quiet morning."), encoding="utf-8")
    evening.write_text(legacy("evening", "2026-07-16", "Reading happened; errands moved."), encoding="utf-8")

    preview = preview_review_migration(vault_root=vault, runtime_dir=runtime)
    assert len(preview.candidates) == 1
    assert preview.candidates[0].state == "ready"
    assert [item.kind for item in preview.candidates[0].sources] == ["evening", "morning"]

    result = apply_review_migration(vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW, idempotency_key="migration")
    assert result.migrated == ("daily-2026-07-16",)
    assert morning.exists() and evening.exists()
    artifact = ReviewArtifactService(vault_root=vault, runtime_dir=runtime).load_id("daily-2026-07-16")
    assert "Protect the quiet morning." in artifact.body
    assert "Reading happened; errands moved." in artifact.body
    assert set(artifact.metadata.migrated_from) == {"reviews/morning-2026-07-16.md", "reviews/evening-2026-07-16.md"}
    assert "Managed old fact" not in artifact.body

    repeated = apply_review_migration(vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW, idempotency_key="migration-again")
    assert repeated.already_migrated == ("daily-2026-07-16",)
    assert repeated.migrated == ()


def test_weekly_legacy_note_uses_iso_week_identity(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; reviews = vault / "reviews"; reviews.mkdir(parents=True)
    source = reviews / "weekly-2026-W29.md"
    source.write_text(legacy("weekly", "2026-07-13", "The week bent toward study."), encoding="utf-8")
    result = apply_review_migration(vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW, idempotency_key="weekly-migration")
    assert result.migrated == ("weekly-2026-W29",)
    artifact = ReviewArtifactService(vault_root=vault, runtime_dir=runtime).load_id("weekly-2026-W29")
    assert artifact.metadata.period_start.isoformat() == "2026-07-13"
    assert "The week bent toward study." in artifact.body
    assert source.exists()


def test_existing_non_pristine_target_and_malformed_legacy_fail_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; reviews = vault / "reviews"; reviews.mkdir(parents=True)
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    artifact = service.open_or_create(kind="daily", day=NOW.date(), timezone="Europe/Istanbul", now=NOW, idempotency_key="open")
    target = vault / artifact.path
    target.write_text(target.read_text(encoding="utf-8").replace("### Orientation", "### Orientation\n\nHuman edit"), encoding="utf-8")
    (reviews / "morning-2026-07-16.md").write_text(legacy("morning", "2026-07-16", "Legacy text"), encoding="utf-8")
    (reviews / "evening-2026-07-17.md").write_text("---\ninvalid: [\n---\nBroken", encoding="utf-8")

    preview = preview_review_migration(vault_root=vault, runtime_dir=runtime)
    states = {item.review_id: item.state for item in preview.candidates}
    assert states["daily-2026-07-16"] == "conflict"
    assert states["daily-2026-07-17"] == "malformed"
    result = apply_review_migration(vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW, idempotency_key="conflict")
    assert {item.review_id for item in result.conflicts} == {"daily-2026-07-16", "daily-2026-07-17"}
    assert "Human edit" in target.read_text(encoding="utf-8")


def test_rebuild_restores_disposable_indexes_from_markdown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; vault.mkdir()
    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    service.open_or_create(kind="daily", day=NOW.date(), timezone="Europe/Istanbul", now=NOW, idempotency_key="daily")
    service.open_or_create(kind="weekly", day=NOW.date(), timezone="Europe/Istanbul", now=NOW, idempotency_key="weekly")
    if runtime.exists():
        import shutil
        shutil.rmtree(runtime)
    result = rebuild_review_state(vault_root=vault, runtime_dir=runtime)
    assert result.artifacts == 2
    assert result.progress_entries == 2
    assert result.history_entries == 2
    assert Path(result.progress_index).exists()
    assert Path(result.history_index).exists()


def test_migration_detects_stale_preview_and_resumes_pristine_target(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; reviews = vault / "reviews"; reviews.mkdir(parents=True)
    source = reviews / "morning-2026-07-16.md"
    source.write_text(legacy("morning", "2026-07-16", "Original reflection."), encoding="utf-8")
    preview = preview_review_migration(vault_root=vault, runtime_dir=runtime)
    expected = {item.path: item.content_hash for item in preview.candidates[0].sources}
    source.write_text(legacy("morning", "2026-07-16", "Changed after preview."), encoding="utf-8")
    stale = apply_review_migration(
        vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW,
        idempotency_key="stale-preview", expected_source_hashes=expected,
    )
    assert stale.migrated == ()
    assert stale.conflicts[0].state == "conflict"
    assert "changed after preview" in stale.conflicts[0].diagnostics[-1].lower()

    service = ReviewArtifactService(vault_root=vault, runtime_dir=runtime)
    service.open_or_create(kind="daily", day=NOW.date(), timezone="Europe/Istanbul", now=NOW, idempotency_key="interrupted-open")
    resumed_preview = preview_review_migration(vault_root=vault, runtime_dir=runtime)
    assert resumed_preview.candidates[0].state == "resumable"
    resumed = apply_review_migration(vault_root=vault, runtime_dir=runtime, actor_id="me", now=NOW, idempotency_key="resume")
    assert resumed.migrated == ("daily-2026-07-16",)
    assert "Changed after preview." in service.load_id("daily-2026-07-16").body


def test_rebuild_reports_unsupported_or_malformed_canonical_artifacts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"; runtime = tmp_path / "runtime"; target = vault / "reviews" / "daily"; target.mkdir(parents=True)
    (target / "2026-07-16.md").write_text("---\ntype: review\nreview_schema: 999\n---\n\n# Unsupported\n", encoding="utf-8")
    result = rebuild_review_state(vault_root=vault, runtime_dir=runtime)
    assert result.artifacts == 1
    assert result.progress_entries == 0
    assert result.history_entries == 0
    assert result.invalid_paths == ("reviews/daily/2026-07-16.md",)
