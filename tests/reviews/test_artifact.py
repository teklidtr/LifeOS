from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError
from lifeos.markdown.parser import parse_markdown_note
from lifeos.reviews.artifact import (
    ReviewArtifactService,
    ReviewArtifactUpdate,
    extract_managed_block,
)

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def service(tmp_path: Path) -> ReviewArtifactService:
    vault = tmp_path / "vault"
    vault.mkdir()
    return ReviewArtifactService(vault_root=vault, runtime_dir=tmp_path / "runtime", actor_id="me")


def test_create_daily_and_weekly_artifacts_with_stable_paths(tmp_path: Path) -> None:
    app = service(tmp_path)
    daily = app.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="Europe/Istanbul",
        now=NOW,
        idempotency_key="open-daily",
    )
    weekly = app.open_or_create(
        kind="weekly",
        day=date(2026, 1, 1),
        timezone="Europe/Istanbul",
        now=NOW,
        idempotency_key="open-weekly",
    )
    assert daily.path == "reviews/daily/2026-07-16.md"
    assert weekly.path == "reviews/weekly/2026-W01.md"
    assert [phase.phase_id for phase in daily.metadata.phases] == ["morning", "evening"]
    assert "## Morning reflection" in daily.body
    assert "## Weekly reflection" in weekly.body


def test_open_is_idempotent_and_update_preserves_human_reflection(tmp_path: Path) -> None:
    app = service(tmp_path)
    first = app.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="Europe/Istanbul",
        now=NOW,
        idempotency_key="open",
    )
    same = app.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="Europe/Istanbul",
        now=NOW,
        idempotency_key="open",
    )
    assert same.content_hash == first.content_hash
    path = app.vault_root / first.path
    path.write_text(
        path.read_text().replace("### Orientation\n", "### Orientation\n\nProtect the morning.\n"),
        encoding="utf-8",
    )
    current = app.load_id(first.metadata.review_id)
    updated = app.update(
        review_id=current.metadata.review_id,
        expected_hash=current.content_hash,
        idempotency_key="refresh",
        now=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
        update=ReviewArtifactUpdate(managed_blocks={"facts": "## Review facts\n\n- New fact"}),
    )
    assert "Protect the morning." in updated.body
    assert extract_managed_block(updated.body, "facts") == "## Review facts\n\n- New fact"


def test_stale_write_and_idempotency_conflict_fail_closed(tmp_path: Path) -> None:
    app = service(tmp_path)
    artifact = app.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open"
    )
    path = app.vault_root / artifact.path
    path.write_text(path.read_text() + "\nManual edit\n", encoding="utf-8")
    with pytest.raises(DailyInteractionError) as stale:
        app.update(
            review_id=artifact.metadata.review_id,
            expected_hash=artifact.content_hash,
            idempotency_key="update",
            now=NOW,
            update=ReviewArtifactUpdate(status="completed"),
        )
    assert stale.value.code == "stale_write"
    current = app.load_id(artifact.metadata.review_id)
    app.update(
        review_id=current.metadata.review_id,
        expected_hash=current.content_hash,
        idempotency_key="same-key",
        now=NOW,
        update=ReviewArtifactUpdate(status="completed"),
    )
    with pytest.raises(DailyInteractionError) as conflict:
        app.update(
            review_id=current.metadata.review_id,
            expected_hash=current.content_hash,
            idempotency_key="same-key",
            now=NOW,
            update=ReviewArtifactUpdate(status="skipped"),
        )
    assert conflict.value.code == "idempotency_conflict"


def test_missing_or_duplicate_managed_block_is_rejected_without_write(tmp_path: Path) -> None:
    app = service(tmp_path)
    artifact = app.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open"
    )
    path = app.vault_root / artifact.path
    original = path.read_text()
    malformed = original.replace("<!-- lifeos:managed:end facts -->", "")
    path.write_text(malformed, encoding="utf-8")
    with pytest.raises(DailyInteractionError) as invalid:
        app.load_id(artifact.metadata.review_id)
    assert invalid.value.code == "invalid_review_artifact"
    assert path.read_text() == malformed


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_managed_refresh_does_not_bridge_from_fenced_example_to_real_block(
    tmp_path: Path,
    newline: str,
) -> None:
    app = service(tmp_path)
    artifact = app.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="UTC",
        now=NOW,
        idempotency_key="open",
    )
    path = app.vault_root / artifact.path
    fake_prefix = (
        "```md\n"
        "<!-- lifeos:managed:start facts -->\n"
        "```\n"
        "Human text between the example and real block must survive.\n"
    )
    real_start = "<!-- lifeos:managed:start facts -->"
    original = path.read_bytes().decode("utf-8")
    parsed = parse_markdown_note(path, content=original)
    body = "\n\n" + parsed.body.replace(real_start, fake_prefix + real_start, 1) + "\n  \n\n"
    original = original[: len(original) - len(parsed.body)] + body.replace("\n", newline)
    path.write_bytes(original.encode("utf-8"))
    before = parse_markdown_note(path, content=original)
    before_block = next(block for block in before.managed_blocks if block.name == "facts")
    current = app.load_id(artifact.metadata.review_id)

    app.update(
        review_id=current.metadata.review_id,
        expected_hash=current.content_hash,
        idempotency_key="refresh",
        now=NOW,
        update=ReviewArtifactUpdate(managed_blocks={"facts": "## Review facts\n\n- New fact"}),
    )

    updated = path.read_bytes().decode("utf-8")
    after = parse_markdown_note(path, content=updated)
    after_block = next(block for block in after.managed_blocks if block.name == "facts")
    assert before.body[: before_block.start_offset] == after.body[: after_block.start_offset]
    assert before.body[before_block.end_offset :] == after.body[after_block.end_offset :]
    assert fake_prefix.replace("\n", newline) in updated
    assert updated.count(real_start) == 2
    assert "- New fact" in updated


def test_fenced_marker_example_cannot_substitute_for_missing_review_block(
    tmp_path: Path,
) -> None:
    app = service(tmp_path)
    artifact = app.open_or_create(
        kind="daily",
        day=date(2026, 7, 16),
        timezone="UTC",
        now=NOW,
        idempotency_key="open",
    )
    path = app.vault_root / artifact.path
    original = path.read_text(encoding="utf-8")
    block_start = original.index("<!-- lifeos:managed:start facts -->")
    block_end = original.index("<!-- lifeos:managed:end facts -->") + len(
        "<!-- lifeos:managed:end facts -->"
    )
    malformed = (
        original[:block_start] + "```md\n<!-- lifeos:managed:start facts -->\nexample\n"
        "<!-- lifeos:managed:end facts -->\n```" + original[block_end:]
    )
    path.write_text(malformed, encoding="utf-8")

    with pytest.raises(DailyInteractionError) as invalid:
        app.load_id(artifact.metadata.review_id)

    assert invalid.value.code == "invalid_review_artifact"
    assert path.read_text(encoding="utf-8") == malformed


def test_duplicate_review_identity_outside_expected_path_is_rejected(tmp_path: Path) -> None:
    app = service(tmp_path)
    legacy = app.vault_root / "reviews" / "duplicate.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\nreview_id: daily-2026-07-16\n---\n", encoding="utf-8")
    with pytest.raises(DailyInteractionError) as duplicate:
        app.open_or_create(
            kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open"
        )
    assert duplicate.value.code == "duplicate_review_identity"
