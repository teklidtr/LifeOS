from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal

import pytest

from lifeos._atomic_write import atomic_write_file_secure
from lifeos.proposals.lifecycle import (
    approve_proposal,
    compute_review_digest,
    serialize_proposal_markdown,
)
from lifeos.proposals.loader import LoadedProposal, load_proposal_directory
from lifeos.proposals.migration import (
    SYNTHETIC_LIFECYCLE_ACTOR,
    SYNTHETIC_REJECTION_REASON,
    LegacyLifecycleMigrationError,
    migrate_legacy_lifecycle,
    migrate_legacy_metadata,
    migrate_legacy_proposal,
    plan_legacy_lifecycle_migration,
)
from lifeos.proposals.patches import PatchDocument, serialize_patch_json_bytes
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalStatus,
    serialize_metadata,
    validate_metadata,
)


def _metadata(
    proposal_id: str,
    status: ProposalStatus,
    *,
    lifecycle_schema_version: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> ProposalMetadata:
    data: dict[str, Any] = {
        "id": proposal_id,
        "schema_version": 1,
        "patch_schema_version": 1,
        "lifecycle_schema_version": lifecycle_schema_version,
        "title": "Legacy proposal",
        "description": "Proposal created before LIFEOS-105.",
        "status": status.value,
        "risk": "low",
        "created_at": "2026-07-01T10:00:00Z",
        "created_by": "system",
        "submitted_at": None,
        "submitted_by": None,
        "review_digest": None,
        "approved_at": None,
        "approved_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "rejection_reason": None,
        "applied_at": None,
        "applied_by": None,
        "related_goals": ["goal-1"],
        "related_sources": ["sources/legacy.md"],
        "extensions": {"legacy": {"source": "bootstrap"}},
    }

    if status is ProposalStatus.APPROVED:
        data["approved_at"] = "2026-07-01T10:02:00Z"
    elif status is ProposalStatus.REJECTED:
        data["rejected_at"] = "2026-07-01T10:03:00Z"
    elif status is ProposalStatus.APPLIED:
        data["approved_at"] = "2026-07-01T10:02:00Z"
        data["applied_at"] = "2026-07-01T10:04:00Z"

    if overrides:
        data.update(overrides)
    return validate_metadata(data)


def _write_proposal(
    proposals_root: Path,
    metadata: ProposalMetadata,
    *,
    body: str = "Legacy body.\n",
) -> tuple[Path, bytes, bytes]:
    proposal_dir = proposals_root / metadata.id
    proposal_dir.mkdir()
    proposal_bytes = serialize_proposal_markdown(metadata, body)
    patch_bytes = serialize_patch_json_bytes(PatchDocument(1, metadata.id, ()))
    (proposal_dir / "proposal.md").write_bytes(proposal_bytes)
    (proposal_dir / "patches.json").write_bytes(patch_bytes)
    return proposal_dir, proposal_bytes, patch_bytes


def _load(proposal_dir: Path, proposals_root: Path) -> LoadedProposal:
    result = load_proposal_directory(proposal_dir, proposals_root=proposals_root)
    assert result.findings == ()
    assert result.proposal is not None
    return result.proposal


@pytest.mark.parametrize("status", list(ProposalStatus))
def test_migrate_legacy_metadata_maps_every_status(status: ProposalStatus) -> None:
    metadata = _metadata("prop-20260701T100000Z-a1b2c3d4", status)
    digest = "sha256:" + "a" * 64

    migrated = migrate_legacy_metadata(metadata, review_digest=digest)

    assert migrated.lifecycle_schema_version == 1
    assert migrated.status is status
    assert migrated.created_at == metadata.created_at
    assert migrated.created_by == metadata.created_by
    assert migrated.related_goals == metadata.related_goals
    assert migrated.related_sources == metadata.related_sources
    assert migrated.extensions == metadata.extensions

    if status is ProposalStatus.DRAFT:
        assert migrated.submitted_at is None
        assert migrated.submitted_by is None
        assert migrated.review_digest is None
    else:
        assert migrated.submitted_at == metadata.created_at
        assert migrated.submitted_by == SYNTHETIC_LIFECYCLE_ACTOR
        assert migrated.review_digest == digest

    if status is ProposalStatus.APPROVED:
        assert migrated.approved_at == metadata.approved_at
        assert migrated.approved_by == SYNTHETIC_LIFECYCLE_ACTOR
    elif status is ProposalStatus.REJECTED:
        assert migrated.rejected_at == metadata.rejected_at
        assert migrated.rejected_by == SYNTHETIC_LIFECYCLE_ACTOR
        assert migrated.rejection_reason == SYNTHETIC_REJECTION_REASON
    elif status is ProposalStatus.APPLIED:
        assert migrated.approved_at == metadata.approved_at
        assert migrated.approved_by == SYNTHETIC_LIFECYCLE_ACTOR
        assert migrated.applied_at == metadata.applied_at
        assert migrated.applied_by == SYNTHETIC_LIFECYCLE_ACTOR

    assert validate_metadata(serialize_metadata(migrated)) == migrated


def test_migrate_rejected_metadata_preserves_recorded_history() -> None:
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.REJECTED,
        overrides={
            "approved_at": "2026-07-01T10:01:00Z",
            "approved_by": "admin",
            "rejected_by": "reviewer",
            "rejection_reason": "Superseded by a safer proposal.",
        },
    )

    migrated = migrate_legacy_metadata(
        metadata,
        review_digest="sha256:" + "b" * 64,
    )

    assert migrated.approved_at == metadata.approved_at
    assert migrated.approved_by == "admin"
    assert migrated.rejected_at == metadata.rejected_at
    assert migrated.rejected_by == "reviewer"
    assert migrated.rejection_reason == "Superseded by a safer proposal."


def test_migrate_non_draft_metadata_rejects_noncanonical_digest() -> None:
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )

    with pytest.raises(LegacyLifecycleMigrationError) as exc_info:
        migrate_legacy_metadata(metadata, review_digest="SHA256:ABC")

    assert exc_info.value.code == "invalid_review_digest"


def test_migrate_metadata_rejects_current_lifecycle() -> None:
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.DRAFT,
        lifecycle_schema_version=1,
    )

    with pytest.raises(LegacyLifecycleMigrationError) as exc_info:
        migrate_legacy_metadata(metadata, review_digest="sha256:" + "c" * 64)

    assert exc_info.value.code == "not_legacy"


def test_plan_is_read_only_and_reports_candidates_skips_and_warnings(
    tmp_path: Path,
) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    legacy = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    current = _metadata(
        "prop-20260701T100100Z-b1c2d3e4",
        ProposalStatus.DRAFT,
        lifecycle_schema_version=1,
    )
    _, legacy_bytes, _ = _write_proposal(proposals_root, legacy)
    _write_proposal(proposals_root, current)
    (proposals_root / "README.txt").write_text("not a proposal", encoding="utf-8")

    plan = plan_legacy_lifecycle_migration(proposals_root)

    assert tuple(candidate.proposal_id for candidate in plan.candidates) == (legacy.id,)
    assert plan.skipped_proposal_ids == (current.id,)
    assert len(plan.warnings) == 1
    assert plan.warnings[0].code == "unexpected_root_file"
    assert (proposals_root / legacy.id / "proposal.md").read_bytes() == legacy_bytes


def test_bulk_migration_is_idempotent_and_preserves_body_and_patches(
    tmp_path: Path,
) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    proposal_dir, original_proposal, patch_bytes = _write_proposal(
        proposals_root,
        metadata,
        body="Legacy body remains byte-for-byte after the frontmatter boundary.\n",
    )

    result = migrate_legacy_lifecycle(proposals_root)

    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.proposal_id == metadata.id
    assert transition.previous_status is ProposalStatus.PENDING
    assert transition.new_status is ProposalStatus.PENDING
    assert transition.write_occurred is True
    assert (proposal_dir / "patches.json").read_bytes() == patch_bytes
    assert (proposal_dir / "proposal.md").read_bytes() != original_proposal

    migrated = _load(proposal_dir, proposals_root)
    assert migrated.body == "Legacy body remains byte-for-byte after the frontmatter boundary.\n"
    assert migrated.metadata.lifecycle_schema_version == 1
    assert migrated.metadata.review_digest == compute_review_digest(
        migrated.metadata,
        migrated.body,
        migrated.patch_document,
    )

    second = migrate_legacy_lifecycle(proposals_root)
    assert second.transitions == ()
    assert second.skipped_proposal_ids == (metadata.id,)


def test_migrated_pending_proposal_can_be_approved(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    proposal_dir, _, _ = _write_proposal(proposals_root, metadata)

    migrate_legacy_lifecycle(proposals_root)
    pending = _load(proposal_dir, proposals_root)
    result = approve_proposal(
        pending,
        proposals_root=proposals_root,
        approved_by="admin",
        approved_at="2026-07-01T10:05:00Z",
    )

    assert result.new_status is ProposalStatus.APPROVED


def test_scan_error_aborts_before_any_write(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    proposal_dir, proposal_bytes, _ = _write_proposal(proposals_root, metadata)

    malformed_dir = proposals_root / "prop-20260701T100100Z-b1c2d3e4"
    malformed_dir.mkdir()
    (malformed_dir / "proposal.md").write_text("not frontmatter", encoding="utf-8")
    (malformed_dir / "patches.json").write_bytes(
        serialize_patch_json_bytes(PatchDocument(1, malformed_dir.name, ()))
    )

    with pytest.raises(LegacyLifecycleMigrationError) as exc_info:
        migrate_legacy_lifecycle(proposals_root)

    assert exc_info.value.code == "scan_failed"
    assert (proposal_dir / "proposal.md").read_bytes() == proposal_bytes


def test_stale_loaded_proposal_is_not_overwritten(tmp_path: Path) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    proposal_dir, _, _ = _write_proposal(proposals_root, metadata)
    loaded = _load(proposal_dir, proposals_root)
    changed_bytes = serialize_proposal_markdown(metadata, "Changed concurrently.\n")
    (proposal_dir / "proposal.md").write_bytes(changed_bytes)

    with pytest.raises(LegacyLifecycleMigrationError) as exc_info:
        migrate_legacy_proposal(loaded, proposals_root=proposals_root)

    assert exc_info.value.code == "stale_proposal_source"
    assert (proposal_dir / "proposal.md").read_bytes() == changed_bytes


def test_migration_uses_lifecycle_atomic_write_primitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.PENDING,
    )
    _write_proposal(proposals_root, metadata)

    calls: list[str] = []
    original = atomic_write_file_secure

    def recording_atomic_write(
        dir_fd: int | None,
        filename: str,
        content: bytes,
        *,
        pre_replace_check: Callable[[], None] | None = None,
    ) -> Literal["confirmed", "uncertain"]:
        calls.append(filename)
        return original(
            dir_fd,
            filename,
            content,
            pre_replace_check=pre_replace_check,
        )

    monkeypatch.setattr(
        "lifeos.proposals.lifecycle.atomic_write_file_secure",
        recording_atomic_write,
    )

    migrate_legacy_lifecycle(proposals_root)

    assert calls == ["proposal.md"]


def test_migrated_review_digest_represents_current_review_envelope(
    tmp_path: Path,
) -> None:
    proposals_root = tmp_path / "proposals"
    proposals_root.mkdir()
    metadata = _metadata(
        "prop-20260701T100000Z-a1b2c3d4",
        ProposalStatus.APPROVED,
    )
    proposal_dir, _, patch_bytes = _write_proposal(proposals_root, metadata)
    legacy = _load(proposal_dir, proposals_root)
    digest_before_migration = compute_review_digest(
        legacy.metadata,
        legacy.body,
        legacy.patch_document,
    )

    migrate_legacy_lifecycle(proposals_root)
    migrated = _load(proposal_dir, proposals_root)

    digest_after_migration = compute_review_digest(
        migrated.metadata,
        migrated.body,
        migrated.patch_document,
    )
    assert migrated.metadata.review_digest == digest_before_migration
    assert migrated.metadata.review_digest == digest_after_migration
    assert len(digest_after_migration) == len("sha256:") + 64
    assert (proposal_dir / "patches.json").read_bytes() == patch_bytes
