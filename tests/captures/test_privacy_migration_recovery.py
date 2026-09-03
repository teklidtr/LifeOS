from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import lifeos.captures.recovery as capture_recovery
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


def test_invalid_privacy_scope_cannot_fall_through_provider_policy(tmp_path: Path) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path)
    path = vault / capture.path
    changed = path.read_text().replace(
        "privacy_scope: standard",
        "privacy_scope: unrestricted",
        1,
    )
    path.write_text(changed)

    with pytest.raises(CaptureError) as exc:
        preview_capture_context(
            vault_root=vault,
            runtime_dir=runtime,
            capture_path=capture.path,
            selected_attachment_ids=(reference.attachment_id,),
            requested_operations=("document-analysis",),
            external_processing_intent=True,
        )

    assert exc.value.code == "invalid_field"
    assert exc.value.data["field"] == "privacy_scope"
    assert path.read_text() == changed


def test_privacy_payload_is_bounded_redacted_and_does_not_traverse_links(tmp_path: Path) -> None:
    vault, runtime, captures, _, capture, reference = attached_capture(tmp_path)
    (vault / "system").mkdir()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\nprotected_prefixes: [diary]\nexternal_allowed_prefixes: [diary]\n"
    )
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
        selected_paths=("diary//private.md",),
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


def test_capture_preview_applies_policy_before_selected_sources_are_read(tmp_path: Path) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path)
    (vault / "system").mkdir()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "excluded_prefixes: [attachments/originals]\n"
        "protected_prefixes: [archive/private]\n"
        "external_allowed_prefixes: []\n"
    )
    (vault / "archive" / "private").mkdir(parents=True)
    (vault / "archive" / "private" / "note.md").write_text("must not be disclosed")

    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        selected_paths=("archive/private/note.md",),
        requested_operations=("document-analysis",),
        external_processing_intent=True,
        allowed_sensitive_roots=("archive/private",),
    )

    reasons = {item.path: item.reason for item in preview.omissions}
    assert reasons[reference.canonical_path] == "excluded-by-policy"
    assert reasons["archive/private/note.md"] == "protected-external-deny"
    assert reference.canonical_path not in preview.provider_payload_paths
    assert "archive/private/note.md" not in preview.provider_payload_paths


def test_capture_preview_denies_protected_primary_before_loading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, capture, _ = attached_capture(tmp_path)
    (vault / "system").mkdir()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\nprotected_prefixes: [captures]\nexternal_allowed_prefixes: []\n"
    )

    real_load = CaptureArtifactService.load
    loaded: list[str] = []

    def recording_load(service: CaptureArtifactService, path: str):
        loaded.append(path)
        return real_load(service, path)

    monkeypatch.setattr(CaptureArtifactService, "load", recording_load)
    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        external_processing_intent=True,
        allow_sensitive_capture=True,
    )

    assert preview.provider_payload_paths == ()
    assert preview.omissions[0].reason == "protected-external-deny"
    assert loaded == []

    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\nprotected_prefixes: [captures]\nexternal_allowed_prefixes: [captures]\n"
    )
    allowed = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        external_processing_intent=True,
        allow_sensitive_capture=True,
    )
    assert capture.path in allowed.provider_payload_paths
    assert loaded == [capture.path]


def test_capture_preview_denies_manifest_before_attachment_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, store, capture, reference = attached_capture(tmp_path)
    (vault / "system").mkdir()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "excluded_prefixes: [attachments/manifests]\n"
        "protected_prefixes: []\n"
        "external_allowed_prefixes: []\n"
    )

    def unexpected_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("attachment manifest was opened before policy allowed it")

    monkeypatch.setattr(store.manifests.__class__, "load", unexpected_load)
    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        external_processing_intent=True,
    )

    assert preview.provider_payload_paths == (capture.path,)
    assert preview.omissions[0].path == reference.manifest_path
    assert preview.omissions[0].reason == "excluded-by-policy"


def test_capture_preview_checks_original_path_from_approved_manifest(tmp_path: Path) -> None:
    vault, runtime, _, _, capture, reference = attached_capture(tmp_path)
    protected_path = "attachments/originals/protected/receipt.txt"
    protected = vault / protected_path
    protected.parent.mkdir(parents=True)
    protected.write_text("SecretName\nTotal: 42")
    manifest_file = vault / reference.manifest_path
    manifest_file.write_text(
        manifest_file.read_text().replace(reference.canonical_path, protected_path)
    )
    (vault / "system").mkdir()
    (vault / "system" / "retrieval-policy.yml").write_text(
        "schema_version: 1\n"
        "protected_prefixes: [attachments/originals/protected]\n"
        "external_allowed_prefixes: []\n"
    )

    preview = preview_capture_context(
        vault_root=vault,
        runtime_dir=runtime,
        capture_path=capture.path,
        selected_attachment_ids=(reference.attachment_id,),
        external_processing_intent=True,
        allow_sensitive_capture=True,
    )

    assert protected_path not in preview.provider_payload_paths
    assert preview.omissions[0].path == protected_path
    assert preview.omissions[0].reason == "protected-external-deny"


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


def _capture_source_bytes(vault: Path) -> dict[str, bytes]:
    return {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in sorted(vault.rglob("*.md"))
    }


def _seed_capture_history(tmp_path: Path, count: int):
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()
    api = CaptureArtifactService(vault_root=vault, runtime_dir=runtime)
    created = [
        api.create(
            title=f"Capture {index}",
            capture_type="meal" if index % 2 == 0 else "exercise",
            now=NOW + timedelta(seconds=index),
        )
        for index in range(count)
    ]
    return vault, runtime, api, created


def test_rebuild_resumes_verified_capture_progress_and_bounds_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _api, _created = _seed_capture_history(tmp_path, 3)
    canonical_before = _capture_source_bytes(vault)
    processed: list[str] = []
    real_process = capture_recovery._process_capture_source

    def recording_process(source):
        processed.append(source.relative_path)
        return real_process(source)

    monkeypatch.setattr(capture_recovery, "_process_capture_source", recording_process)

    first = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    second = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    third = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )

    assert [len(first.entries), len(second.entries), len(third.entries)] == [1, 2, 3]
    assert len(processed) == 3
    assert len(set(processed)) == 3
    checkpoint = runtime / "captures" / "rebuild-checkpoint.json"
    assert json.loads(checkpoint.read_text())["next_index"] == 3

    resumed = rebuild_capture_index(vault_root=vault, runtime_dir=runtime, batch_size=1)
    assert resumed.state == "ready"
    assert len(resumed.entries) == 3
    assert not checkpoint.exists()
    assert _capture_source_bytes(vault) == canonical_before

    shutil.rmtree(runtime / "captures")
    fresh = rebuild_capture_index(vault_root=vault, runtime_dir=runtime, batch_size=1)
    assert resumed.entries == fresh.entries
    assert resumed.diagnostics == fresh.diagnostics


@pytest.mark.parametrize(
    "payload",
    [
        "{",
        '{"schema": 999, "next_index": 1}',
        '{"schema": 2, "source_signature": "sha256:forged"}',
    ],
)
def test_rebuild_discards_invalid_capture_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    vault, runtime, _api, _created = _seed_capture_history(tmp_path, 2)
    first = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert first.state == "interrupted"
    checkpoint = runtime / "captures" / "rebuild-checkpoint.json"
    checkpoint.write_text(payload)

    processed: list[str] = []
    real_process = capture_recovery._process_capture_source

    def recording_process(source):
        processed.append(source.relative_path)
        return real_process(source)

    monkeypatch.setattr(capture_recovery, "_process_capture_source", recording_process)
    restarted = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )

    assert restarted.state == "interrupted"
    assert len(processed) == 1
    checkpoint_data = json.loads(checkpoint.read_text())
    assert checkpoint_data["schema"] == 2
    assert checkpoint_data["next_index"] == 1
    assert isinstance(checkpoint_data["checkpoint_digest"], str)


@pytest.mark.parametrize(
    "change", ["edit", "add", "move", "delete", "duplicate", "unsupported", "malformed"]
)
def test_capture_checkpoint_is_invalidated_when_canonical_sources_change(
    tmp_path: Path, change: str
) -> None:
    vault, runtime, api, created = _seed_capture_history(tmp_path, 3)
    first = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert first.state == "interrupted"
    checkpoint = runtime / "captures" / "rebuild-checkpoint.json"
    first_signature = json.loads(checkpoint.read_text())["source_signature"]
    source = vault / created[0].path

    if change == "edit":
        source.write_text(source.read_text() + "\ncheckpoint source edit\n")
    elif change == "add":
        api.create(
            title="Added capture",
            capture_type="meal",
            now=NOW + timedelta(minutes=1),
        )
    elif change == "move":
        moved = vault / "archive" / "moved-after-interruption.md"
        moved.parent.mkdir()
        source.rename(moved)
    elif change == "delete":
        source.unlink()
    elif change == "duplicate":
        duplicate = source.with_name("duplicate-after-interruption.md")
        duplicate.write_bytes(source.read_bytes())
    elif change == "unsupported":
        source.write_text(source.read_text().replace("schema_version: 1", "schema_version: 999", 1))
    else:
        source.write_text(
            source.read_text().replace(
                "<!-- lifeos:managed:end rich-capture -->",
                "<!-- lifeos:managed:end broken-capture -->",
                1,
            )
        )

    canonical_after_change = _capture_source_bytes(vault)
    restarted = rebuild_capture_index(
        vault_root=vault, runtime_dir=runtime, batch_size=1, interrupt_after=1
    )
    assert restarted.state == "interrupted"
    second_signature = json.loads(checkpoint.read_text())["source_signature"]
    assert second_signature != first_signature

    resumed = rebuild_capture_index(vault_root=vault, runtime_dir=runtime, batch_size=1)
    assert resumed.state == "ready"
    assert _capture_source_bytes(vault) == canonical_after_change

    shutil.rmtree(runtime / "captures")
    fresh = rebuild_capture_index(vault_root=vault, runtime_dir=runtime, batch_size=1)
    assert resumed.entries == fresh.entries
    assert resumed.diagnostics == fresh.diagnostics


def test_capture_rebuild_empty_sources_are_ready_and_checkpoint_free(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    runtime = tmp_path / "runtime"
    vault.mkdir()

    rebuilt = rebuild_capture_index(vault_root=vault, runtime_dir=runtime, batch_size=1)

    assert rebuilt.state == "ready"
    assert rebuilt.entries == ()
    assert rebuilt.diagnostics == ()
    assert not (runtime / "captures" / "rebuild-checkpoint.json").exists()
