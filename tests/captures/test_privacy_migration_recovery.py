from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import CaptureError
from lifeos.captures.extraction import ExtractionResult, LocalExtractionService
from lifeos.captures.migration import apply_capture_migration, preview_capture_migration
from lifeos.captures.privacy import preview_capture_context
from lifeos.captures.recovery import (
    audit_capture_recovery,
    load_capture_index,
    rebuild_capture_index,
)
from lifeos.captures.storage import AttachmentStore

NOW = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)


def attached_capture(tmp_path: Path, *, protected: bool = False):
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    captures = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)
    capture = captures.create(
        title="Receipt",
        capture_type="attachment",
        description="SecretName bought soup",
        privacy_scope="protected" if protected else "standard",
        sensitive=protected,
        now=NOW,
    )
    source = tmp_path / "receipt.txt"
    source.write_text("SecretName\nTotal: 42")
    store = AttachmentStore(vault_root=vault, runtime_dir=runtime)
    imported = store.import_file(
        source,
        capture_source="test",
        parent_capture_id=capture.metadata.capture_id,
        now=NOW,
    )
    capture = store.attach_to_capture(
        capture.path,
        imported.reference,
        expected_hash=capture.content_hash,
        now=NOW,
    )
    extraction = ExtractionResult(
        imported.reference.attachment_id,
        imported.reference.content_hash,
        "utf8-text",
        "1",
        "completed",
        text="SecretName\nTotal: 42",
        quality="high",
    )
    LocalExtractionService(vault_root=vault, runtime_dir=runtime).publish(extraction)
    return vault, runtime, captures, store, capture, imported.reference


def test_privacy_requires_explicit_intent_and_protected_scope(tmp_path: Path) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path, protected=True)
    denied = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        requested_operations=("document-analysis",),
    )
    assert denied.provider_payload_paths == ()
    assert {item.reason for item in denied.omissions} == {"explicit-processing-intent-required"}
    protected = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        requested_operations=("document-analysis",),
        external_processing_intent=True,
    )
    assert protected.provider_payload_paths == ()
    assert {item.reason for item in protected.omissions} == {"protected-default-deny"}


def test_privacy_payload_is_bounded_redacted_and_does_not_traverse_links(tmp_path: Path) -> None:
    vault, runtime, captures, _, capture, reference = attached_capture(tmp_path)
    (vault / "diary").mkdir()
    (vault / "diary" / "private.md").write_text("SecretName private context " + "x" * 200)
    capture = captures.save(
        capture,
        replace(
            capture.metadata,
            links=(),
        ),
        expected_hash=capture.content_hash,
    )
    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        selected_paths=("diary/private.md",),
        requested_operations=("document-analysis",),
        external_processing_intent=True,
        allowed_sensitive_roots=("diary",),
        redact_terms=("SecretName",),
        max_item_bytes=80,
        max_total_bytes=200,
    )
    assert capture.path in preview.provider_payload_paths
    assert reference.canonical_path in preview.provider_payload_paths
    assert "diary/private.md" in preview.provider_payload_paths
    assert all("SecretName" not in item.excerpt for item in preview.items)
    assert any("[REDACTED-1]" in item.excerpt for item in preview.items)
    assert preview.total_bytes <= 200
    assert preview.truncated is True
    assert "does not upload" in preview.disclosure


def test_changed_attachment_is_blocked_from_provider_preview(tmp_path: Path) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path)
    (vault / reference.canonical_path).write_text("changed")
    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        requested_operations=("document-analysis",),
        external_processing_intent=True,
    )
    assert any(item.reason == "attachment-changed" for item in preview.omissions)
    assert reference.canonical_path not in preview.provider_payload_paths


def test_migration_is_an_audited_no_op_when_no_legacy_schema_exists(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    preview = preview_capture_migration(vault_root=vault, runtime_dir=runtime)
    assert preview.candidates == ()
    assert preview.legacy_formats_found == ()
    result = apply_capture_migration(vault_root=vault, runtime_dir=runtime)
    assert result.state == "not-required"
    assert (runtime / result.audit_path).exists()
    assert json.loads((runtime / result.audit_path).read_text())["state"] == "not-required"
    with pytest.raises(CaptureError) as exc:
        apply_capture_migration(
            vault_root=vault,
            runtime_dir=runtime,
            expected_source_hashes={"tracking/invented.md": "sha256:x"},
        )
    assert exc.value.code == "unknown_legacy_source"


def test_recovery_rebuilds_index_and_missing_manifest_from_canonical_sources(
    tmp_path: Path,
) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path)
    (vault / reference.manifest_path).unlink()
    initial = audit_capture_recovery(vault_root=vault, runtime_dir=runtime, rebuild=True)
    assert any(item["code"] == "missing_manifest" for item in initial.diagnostics)
    repaired = audit_capture_recovery(
        vault_root=vault,
        runtime_dir=runtime,
        rebuild=True,
        rebuild_manifests=True,
    )
    assert reference.manifest_path in repaired.rebuilt_manifests
    assert (vault / reference.manifest_path).exists()
    assert (
        load_capture_index(runtime_dir=runtime).entries[0].capture_id == capture.metadata.capture_id
    )


def test_recovery_detects_moves_duplicates_missing_changed_stale_and_orphans(
    tmp_path: Path,
) -> None:
    vault, runtime, _, store, capture, reference = attached_capture(tmp_path)
    rebuild_capture_index(vault_root=vault, runtime_dir=runtime)
    moved = vault / "archive" / "moved-capture.md"
    moved.parent.mkdir()
    (vault / capture.path).rename(moved)
    duplicate = vault / "captures" / "2026" / "duplicate.md"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(moved.read_text())
    (vault / reference.canonical_path).write_text("changed bytes")
    extractor = LocalExtractionService(vault_root=vault, runtime_dir=runtime)
    extractor.publish(
        ExtractionResult(
            reference.attachment_id,
            "sha256:" + "0" * 64,
            "ocr",
            "1",
            "completed",
            text="stale",
            quality="low",
        )
    )
    orphan = vault / "attachments" / "originals" / "orphan.bin"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan")
    report = audit_capture_recovery(vault_root=vault, runtime_dir=runtime, rebuild=True)
    codes = {item["code"] for item in report.diagnostics}
    assert {
        "moved_artifact",
        "duplicate_identity",
        "attachment_changed",
        "stale_extraction",
        "orphan_original",
    } <= codes
    assert store.audit(reference.attachment_id).status == "changed"


def test_runtime_deletion_and_interrupted_large_rebuild_are_recoverable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    captures = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)
    for offset in range(70):
        captures.create(
            title=f"Capture {offset}",
            capture_type="meal" if offset % 2 == 0 else "exercise",
            now=NOW + timedelta(seconds=offset),
        )
    interrupted = audit_capture_recovery(
        vault_root=vault,
        runtime_dir=runtime,
        rebuild=True,
        batch_size=7,
        interrupt_after=10,
    )
    assert interrupted.state == "interrupted"
    assert interrupted.index.checkpoint_path is not None
    recovered = audit_capture_recovery(
        vault_root=vault,
        runtime_dir=runtime,
        rebuild=True,
        delete_runtime=True,
        batch_size=11,
    )
    assert recovered.index.state == "ready"
    assert len(recovered.index.entries) == 70
    assert not (runtime / "captures" / "rebuild-checkpoint.json").exists()
