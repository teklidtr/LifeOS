from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import AttachmentManifestService, CaptureArtifactService
from lifeos.captures.contracts import (
    AttachmentManifest,
    AttachmentReference,
    CaptureError,
    DerivedValue,
    LifecycleEvent,
    validate_transition,
)

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)


def test_create_load_and_human_annotations_survive_managed_update(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = service.create(
        title="Lunch", capture_type="meal", description="Soup", source_entry_point="ribbon", now=NOW
    )
    path = tmp_path / capture.path
    content = path.read_text()
    path.write_text(
        content.replace("## User annotations\n", "## User annotations\n\nTasted salty.\n")
    )
    opened = service.load(capture.path)
    updated = service.update_user_fields(
        opened.path, expected_hash=opened.content_hash, description="Soup and bread", now=NOW
    )
    assert updated.metadata.description == "Soup and bread"
    assert "Tasted salty." in updated.human_body
    assert updated.metadata.capture_type == "meal"


def test_capture_stale_write_and_invalid_transition_fail_closed(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = service.create(title="Run", capture_type="exercise", now=NOW)
    current = service.transition(
        capture.path, "completed", expected_hash=capture.content_hash, now=NOW
    )
    with pytest.raises(CaptureError, match="changed") as stale:
        service.update_user_fields(
            capture.path, expected_hash=capture.content_hash, description="stale", now=NOW
        )
    assert stale.value.code == "stale_capture"
    with pytest.raises(CaptureError) as invalid:
        service.transition(current.path, "processing", expected_hash=current.content_hash, now=NOW)
    assert invalid.value.code == "invalid_transition"


def test_unknown_value_is_not_zero_or_false_precision() -> None:
    unknown = DerivedValue("calories", None, "kcal", "unknown")
    assert unknown.value is None
    with pytest.raises(CaptureError):
        DerivedValue("calories", 500, "kcal", "unknown")
    estimate = DerivedValue("calories", None, "kcal", "image-estimate", "low", 400, 700)
    assert estimate.range_low == 400
    assert estimate.range_high == 700


@pytest.mark.parametrize(
    ("field", "valid_value"),
    [
        ("capture_type", "meal"),
        ("state", "captured"),
        ("privacy_scope", "standard"),
        ("extraction_status", "not-requested"),
        ("enrichment_status", "not-requested"),
    ],
)
def test_persisted_capture_enums_fail_closed(
    tmp_path: Path,
    field: str,
    valid_value: str,
) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = service.create(title="Meal", capture_type="meal", now=NOW)
    path = tmp_path / capture.path
    changed = path.read_text().replace(
        f"{field}: {valid_value}",
        f"{field}: unsupported-value",
        1,
    )
    path.write_text(changed)

    with pytest.raises(CaptureError) as exc:
        service.load(capture.path)

    assert exc.value.code == "invalid_field"
    assert exc.value.data["field"] == field
    assert path.read_text() == changed


@pytest.mark.parametrize(
    "field",
    [
        "sensitive",
        "exclude_from_semantic",
        "exclude_from_conversations",
        "exclude_from_reviews",
        "exclude_from_experiments",
    ],
)
def test_persisted_capture_policy_flags_require_booleans(tmp_path: Path, field: str) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = service.create(title="Meal", capture_type="meal", now=NOW)
    path = tmp_path / capture.path
    changed = path.read_text().replace(f"{field}: false", f"{field}: {{}}", 1)
    path.write_text(changed)

    with pytest.raises(CaptureError) as exc:
        service.load(capture.path)

    assert exc.value.code == "invalid_field"
    assert exc.value.data["field"] == field
    assert path.read_text() == changed


@pytest.mark.parametrize(
    "field",
    ["kind", "extraction_status", "preview_status", "transcript_status", "redaction_state"],
)
def test_attachment_manifest_enums_fail_closed(field: str) -> None:
    metadata = AttachmentManifest(
        attachment_id="att-0123456789abcdef",
        content_hash="sha256:" + "a" * 64,
        original_filename="file.txt",
        canonical_path="attachments/originals/aa/hash/file.txt",
        media_type="text/plain",
        byte_size=1,
        capture_source="test",
        imported_at=NOW.isoformat(),
    )

    with pytest.raises(CaptureError) as exc:
        replace(metadata, **{field: "unsupported-value"})

    assert exc.value.code == "invalid_field"
    assert exc.value.data["field"] == field


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("derived source", {"source": "unsupported-value"}),
        ("derived confidence", {"confidence": "unsupported-value"}),
        ("derived status", {"status": "unsupported-value"}),
    ],
)
def test_derived_value_enums_fail_closed(field: str, kwargs: dict[str, str]) -> None:
    values = {"source": "user-entered", "confidence": "high", "status": "suggested"}
    values.update(kwargs)

    with pytest.raises(CaptureError) as exc:
        DerivedValue("calories", 10, "kcal", **values)  # type: ignore[arg-type]

    assert exc.value.code == "invalid_field"
    assert exc.value.data["field"] == field


def test_lifecycle_and_transition_states_fail_closed() -> None:
    with pytest.raises(CaptureError) as from_state:
        LifecycleEvent("life-1", "unsupported", "captured", NOW.isoformat())
    assert from_state.value.data["field"] == "lifecycle from_state"

    with pytest.raises(CaptureError) as to_state:
        LifecycleEvent("life-1", None, "unsupported", NOW.isoformat())  # type: ignore[arg-type]
    assert to_state.value.data["field"] == "lifecycle to_state"

    with pytest.raises(CaptureError) as transition:
        validate_transition("unsupported", "captured")  # type: ignore[arg-type]
    assert transition.value.data["field"] == "current state"


def test_manifest_round_trip_and_human_annotations(tmp_path: Path) -> None:
    service = AttachmentManifestService(vault_root=tmp_path)
    metadata = AttachmentManifest(
        attachment_id="att-0123456789abcdef",
        content_hash="sha256:" + "a" * 64,
        original_filename="meal.jpg",
        canonical_path="attachments/originals/aa/hash/meal.jpg",
        media_type="image/jpeg",
        byte_size=123,
        capture_source="clipboard",
        imported_at=NOW.isoformat(),
    )
    created = service.create(metadata, human_body="## User annotations\n\nKeep original.\n")
    updated = service.save(
        created,
        replace(created.metadata, preview_status="completed"),
        expected_hash=created.content_hash,
    )
    assert updated.metadata.preview_status == "completed"
    assert "Keep original." in updated.human_body


@pytest.mark.parametrize(
    "canonical_path",
    [
        "../outside.txt",
        "/attachments/originals/aa/hash/file.txt",
        "C:/attachments/originals/aa/hash/file.txt",
        "attachments/originals/aa/../file.txt",
        "attachments/originals//aa/hash/file.txt",
        "attachments\\originals\\aa\\hash\\file.txt",
        "wiki/file.txt",
    ],
)
def test_attachment_canonical_paths_are_confined_to_original_storage(
    canonical_path: str,
) -> None:
    with pytest.raises(CaptureError) as manifest_error:
        AttachmentManifest(
            attachment_id="att-0123456789abcdef",
            content_hash="sha256:" + "a" * 64,
            original_filename="file.txt",
            canonical_path=canonical_path,
            media_type="text/plain",
            byte_size=1,
            capture_source="test",
            imported_at=NOW.isoformat(),
        )
    assert manifest_error.value.code == "invalid_attachment_path"

    with pytest.raises(CaptureError) as reference_error:
        AttachmentReference(
            attachment_id="att-0123456789abcdef",
            manifest_path="attachments/manifests/att-0123456789abcdef.md",
            content_hash="sha256:" + "a" * 64,
            media_type="text/plain",
            byte_size=1,
            original_filename="file.txt",
            canonical_path=canonical_path,
        )
    assert reference_error.value.code == "invalid_attachment_path"


@pytest.mark.parametrize(
    "manifest_path",
    [
        "../manifest.md",
        "/attachments/manifests/att-0123456789abcdef.md",
        "attachments/manifests/../att-0123456789abcdef.md",
        "attachments/manifests//att-0123456789abcdef.md",
        "captures/2026/not-a-manifest.md",
    ],
)
def test_attachment_manifest_references_are_confined_to_manifest_storage(
    manifest_path: str,
) -> None:
    with pytest.raises(CaptureError) as exc:
        AttachmentReference(
            attachment_id="att-0123456789abcdef",
            manifest_path=manifest_path,
            content_hash="sha256:" + "a" * 64,
            media_type="text/plain",
            byte_size=1,
            original_filename="file.txt",
            canonical_path="attachments/originals/aa/hash/file.txt",
        )
    assert exc.value.code == "invalid_attachment_path"


def test_unsupported_schema_fails_without_rewriting(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    capture = service.create(title="Receipt", capture_type="attachment", now=NOW)
    path = tmp_path / capture.path
    original = path.read_text()
    path.write_text(original.replace("schema_version: 1", "schema_version: 99", 1))
    changed = path.read_text()
    with pytest.raises(CaptureError) as exc:
        service.load(capture.path)
    assert exc.value.code == "unsupported_schema"
    assert path.read_text() == changed


def test_list_filters_capture_types_and_states(tmp_path: Path) -> None:
    service = CaptureArtifactService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    meal = service.create(title="Meal", capture_type="meal", now=NOW)
    service.create(title="Walk", capture_type="exercise", now=NOW)
    done = service.transition(meal.path, "completed", expected_hash=meal.content_hash, now=NOW)
    assert [
        item.metadata.capture_id
        for item in service.list(capture_types=frozenset({"meal"}), states=frozenset({"completed"}))
    ] == [done.metadata.capture_id]
