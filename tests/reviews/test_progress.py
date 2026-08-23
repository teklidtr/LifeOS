from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from lifeos.daily import DailyInteractionError
from lifeos.reviews import ReviewArtifactService
from lifeos.reviews.progress import ReviewProgressService, rebuild_progress_cache

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def setup(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    artifacts = ReviewArtifactService(vault_root=vault, runtime_dir=runtime, actor_id="me")
    artifact = artifacts.open_or_create(
        kind="daily", day=date(2026, 7, 16), timezone="UTC", now=NOW, idempotency_key="open"
    )
    return vault, runtime, artifacts, ReviewProgressService(artifacts), artifact


def test_progress_answers_and_reflection_are_canonical_and_survive_cache_deletion(
    tmp_path: Path,
) -> None:
    vault, runtime, artifacts, progress, artifact = setup(tmp_path)
    path = vault / artifact.path
    path.write_text(
        path.read_text().replace(
            "### Orientation\n", "### Orientation\n\nDo less, deliberately.\n"
        ),
        encoding="utf-8",
    )
    artifact = artifacts.load_id(artifact.metadata.review_id)
    artifact = progress.update_section(
        review_id=artifact.metadata.review_id,
        phase_id="morning",
        section_id="plans",
        action="complete",
        expected_hash=artifact.content_hash,
        idempotency_key="section",
        now=NOW,
    )
    artifact = progress.answer(
        review_id=artifact.metadata.review_id,
        prompt_id="morning-intent",
        value="Protect reading time",
        phase_id="morning",
        expected_hash=artifact.content_hash,
        idempotency_key="answer",
        now=NOW,
    )
    assert artifact.metadata.phases[0].completed_sections == ("plans",)
    assert artifact.metadata.answers[0].value == "Protect reading time"
    assert "Do less, deliberately." in artifact.body
    if runtime.exists():
        import shutil

        shutil.rmtree(runtime)
    loaded = ReviewArtifactService(vault_root=vault, runtime_dir=runtime).load_id(
        artifact.metadata.review_id
    )
    assert loaded.metadata.answers[0].value == "Protect reading time"
    assert loaded.metadata.phases[0].completed_sections == ("plans",)


def test_phase_and_review_completion_require_explicit_accounting(tmp_path: Path) -> None:
    _, _, _, progress, artifact = setup(tmp_path)
    with pytest.raises(DailyInteractionError) as incomplete:
        progress.update_phase(
            review_id=artifact.metadata.review_id,
            phase_id="morning",
            action="complete",
            required_sections=("plans",),
            expected_hash=artifact.content_hash,
            idempotency_key="phase",
            now=NOW,
        )
    assert incomplete.value.code == "review_phase_incomplete"
    artifact = progress.update_section(
        review_id=artifact.metadata.review_id,
        phase_id="morning",
        section_id="plans",
        action="skip",
        expected_hash=artifact.content_hash,
        idempotency_key="skip-section",
        now=NOW,
    )
    artifact = progress.update_phase(
        review_id=artifact.metadata.review_id,
        phase_id="morning",
        action="complete",
        required_sections=("plans",),
        expected_hash=artifact.content_hash,
        idempotency_key="complete-morning",
        now=NOW,
    )
    with pytest.raises(DailyInteractionError) as pending:
        progress.complete_review(
            review_id=artifact.metadata.review_id,
            expected_hash=artifact.content_hash,
            idempotency_key="complete-review",
            now=NOW,
        )
    assert pending.value.code == "review_incomplete"
    artifact = progress.update_phase(
        review_id=artifact.metadata.review_id,
        phase_id="evening",
        action="skip",
        required_sections=(),
        expected_hash=artifact.content_hash,
        idempotency_key="skip-evening",
        now=NOW,
    )
    artifact = progress.complete_review(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key="complete-review-2",
        now=NOW,
    )
    assert artifact.metadata.status == "completed"
    assert artifact.metadata.lifecycle_events[-1].transition == "completed"


def test_skip_and_reopen_are_explicit_lifecycle_events(tmp_path: Path) -> None:
    _, _, _, progress, artifact = setup(tmp_path)
    artifact = progress.skip_review(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key="skip",
        now=NOW,
        note="Travel day",
    )
    assert artifact.metadata.status == "skipped"
    assert all(phase.state == "skipped" for phase in artifact.metadata.phases)
    artifact = progress.reopen_review(
        review_id=artifact.metadata.review_id,
        expected_hash=artifact.content_hash,
        idempotency_key="reopen",
        now=NOW,
    )
    assert artifact.metadata.status == "open"
    assert [event.transition for event in artifact.metadata.lifecycle_events] == [
        "skipped",
        "reopened",
    ]


def test_progress_cache_rebuilds_from_markdown(tmp_path: Path) -> None:
    vault, runtime, _, progress, artifact = setup(tmp_path)
    artifact = progress.update_section(
        review_id=artifact.metadata.review_id,
        phase_id="morning",
        section_id="inbox",
        action="complete",
        expected_hash=artifact.content_hash,
        idempotency_key="section",
        now=NOW,
    )
    rows = rebuild_progress_cache(vault_root=vault, runtime_dir=runtime)
    assert rows[artifact.metadata.review_id]["path"] == artifact.path
    assert (runtime / "reviews" / "progress-index.json").exists()
