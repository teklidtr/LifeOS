from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import CaptureError
from lifeos.captures.extraction import ExtractionCancellation, LocalExtractionService
from lifeos.captures.processing import CaptureProcessingService
from lifeos.captures.storage import AttachmentStore

NOW = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)


def services(tmp_path: Path) -> tuple[CaptureArtifactService, AttachmentStore, CaptureProcessingService]:
    runtime = tmp_path / ".lifeos"
    return CaptureArtifactService(vault_root=tmp_path, runtime_dir=runtime), AttachmentStore(vault_root=tmp_path, runtime_dir=runtime), CaptureProcessingService(vault_root=tmp_path, runtime_dir=runtime)


def test_exact_duplicate_reuses_original_and_same_name_different_content_does_not(tmp_path: Path) -> None:
    _, store, _ = services(tmp_path)
    first = tmp_path / "source-a" / "receipt.txt"; first.parent.mkdir(); first.write_text("one")
    second = tmp_path / "source-b" / "receipt.txt"; second.parent.mkdir(); second.write_text("two")
    a = store.import_file(first, capture_source="drop", now=NOW)
    duplicate = store.import_file(first, capture_source="drop", now=NOW)
    b = store.import_file(second, capture_source="drop", now=NOW)
    assert duplicate.duplicate and duplicate.reused_original
    assert a.reference.canonical_path == duplicate.reference.canonical_path
    assert a.reference.content_hash != b.reference.content_hash
    assert a.reference.canonical_path != b.reference.canonical_path


def test_independent_copy_preserves_separate_manifest(tmp_path: Path) -> None:
    _, store, _ = services(tmp_path)
    source = tmp_path / "photo.bin"; source.write_bytes(b"same")
    first = store.import_file(source, capture_source="camera", now=NOW)
    second = store.import_file(source, capture_source="camera", independent_copy=True, now=NOW)
    assert first.reference.attachment_id != second.reference.attachment_id
    assert second.duplicate and not second.reused_original


def test_attach_remove_and_safe_delete_reference_checks(tmp_path: Path) -> None:
    captures, store, _ = services(tmp_path)
    source = tmp_path / "note.txt"; source.write_text("hello")
    imported = store.import_file(source, capture_source="clipboard", now=NOW)
    capture = captures.create(title="Note", capture_type="attachment", now=NOW)
    linked = store.attach_to_capture(capture.path, imported.reference, expected_hash=capture.content_hash, now=NOW)
    with pytest.raises(CaptureError) as referenced:
        store.delete_original_if_unreferenced(imported.reference.attachment_id)
    assert referenced.value.code == "attachment_referenced"
    unlinked = store.remove_from_capture(capture.path, imported.reference.attachment_id, expected_hash=linked.content_hash, now=NOW)
    assert not unlinked.metadata.attachments
    assert store.delete_original_if_unreferenced(imported.reference.attachment_id)


def test_local_text_and_image_metadata_extraction(tmp_path: Path) -> None:
    _, store, _ = services(tmp_path)
    text = tmp_path / "note.md"; text.write_text("# Hello\n")
    png = tmp_path / "tiny.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (2).to_bytes(4, "big") + (3).to_bytes(4, "big") + b"x")
    text_manifest = store.manifests.load(store.import_file(text, capture_source="drop", now=NOW).manifest_path)
    image_manifest = store.manifests.load(store.import_file(png, capture_source="drop", now=NOW).manifest_path)
    extractor = LocalExtractionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos")
    assert "Hello" in extractor.extract(text_manifest.metadata).text
    image = extractor.extract(image_manifest.metadata)
    assert image.metadata == {"format": "png", "width": 2, "height": 3}


def test_unsupported_and_oversized_files_remain_preserved(tmp_path: Path) -> None:
    _, store, _ = services(tmp_path)
    arbitrary = tmp_path / "data.unknown"; arbitrary.write_bytes(b"abc")
    big = tmp_path / "big.txt"; big.write_text("x" * 20)
    a = store.manifests.load(store.import_file(arbitrary, capture_source="drop", now=NOW).manifest_path)
    b = store.manifests.load(store.import_file(big, capture_source="drop", now=NOW).manifest_path)
    extractor = LocalExtractionService(vault_root=tmp_path, runtime_dir=tmp_path / ".lifeos", max_text_bytes=10)
    assert extractor.extract(a.metadata).status == "unavailable"
    with pytest.raises(CaptureError) as exc:
        extractor.extract(b.metadata)
    assert exc.value.code == "oversized_for_extraction"
    assert (tmp_path / b.metadata.canonical_path).exists()


def test_interrupted_processing_resumes_without_losing_capture(tmp_path: Path) -> None:
    captures, store, processing = services(tmp_path)
    one = tmp_path / "one.txt"; one.write_text("one")
    two = tmp_path / "two.txt"; two.write_text("two")
    refs = (store.import_file(one, capture_source="drop", now=NOW).reference, store.import_file(two, capture_source="drop", now=NOW).reference)
    capture = captures.create(title="Files", capture_type="attachment", attachments=refs, now=NOW)
    job = processing.start_extraction(capture.path, expected_hash=capture.content_hash, now=NOW)
    token = ExtractionCancellation(); token.cancel()
    stopped = processing.run_extraction(job.job_id, cancellation=token, now=NOW)
    assert stopped.state == "cancelled"
    retried = processing.retry(job.job_id, now=NOW)
    finished = processing.run_extraction(retried.job_id, now=NOW)
    assert finished.state == "completed"
    assert len(finished.completed_attachment_ids) == 2
    assert captures.load(capture.path).metadata.state == "enriched"


def test_changed_and_missing_attachment_audit(tmp_path: Path) -> None:
    _, store, _ = services(tmp_path)
    source = tmp_path / "file.txt"; source.write_text("original")
    imported = store.import_file(source, capture_source="drop", now=NOW)
    canonical = tmp_path / imported.reference.canonical_path
    canonical.write_text("changed")
    assert store.audit(imported.reference.attachment_id).status == "changed"
    canonical.unlink()
    assert store.audit(imported.reference.attachment_id).status == "missing"


def test_merge_and_split_preserve_references_and_archive_sources(tmp_path: Path) -> None:
    captures, store, processing = services(tmp_path)
    a_file = tmp_path / "a.txt"; a_file.write_text("a")
    b_file = tmp_path / "b.txt"; b_file.write_text("b")
    a_ref = store.import_file(a_file, capture_source="drop", now=NOW).reference
    b_ref = store.import_file(b_file, capture_source="drop", now=NOW).reference
    a = captures.create(title="A", capture_type="attachment", attachments=(a_ref,), now=NOW)
    b = captures.create(title="B", capture_type="attachment", attachments=(b_ref,), now=NOW)
    preview = processing.merge_preview((a.path, b.path))
    merged = processing.apply_merge(preview, now=NOW)
    assert {item.attachment_id for item in merged.metadata.attachments} == {a_ref.attachment_id, b_ref.attachment_id}
    assert captures.load(a.path).metadata.state == "archived"
    parts = processing.split(merged.path, ((a_ref.attachment_id,), (b_ref.attachment_id,)), expected_hash=merged.content_hash, now=NOW)
    assert len(parts) == 2
    assert all(item.metadata.split_from == merged.metadata.capture_id for item in parts)
