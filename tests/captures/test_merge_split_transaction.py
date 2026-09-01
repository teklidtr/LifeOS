from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lifeos.captures.artifact import CaptureArtifactService
from lifeos.captures.contracts import CaptureArtifact, CaptureError
from lifeos.captures.processing import CaptureProcessingService
from lifeos.captures.recovery import audit_capture_recovery
from lifeos.captures.storage import AttachmentStore
from lifeos.captures.transaction import (
    CaptureFileWrite,
    CaptureTransactionError,
    execute_capture_transaction,
    recover_capture_transactions,
)
from lifeos.proposals.recovery_store import acquire_pinned_recovery_store

NOW = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)


def services(
    tmp_path: Path,
) -> tuple[Path, Path, CaptureArtifactService, AttachmentStore, CaptureProcessingService]:
    vault = tmp_path / "vault"
    vault.mkdir()
    runtime = tmp_path / "runtime"
    return (
        vault,
        runtime,
        CaptureArtifactService(vault_root=vault, runtime_dir=runtime),
        AttachmentStore(vault_root=vault, runtime_dir=runtime),
        CaptureProcessingService(vault_root=vault, runtime_dir=runtime),
    )


def source_pair(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    CaptureArtifactService,
    AttachmentStore,
    CaptureProcessingService,
    CaptureArtifact,
    CaptureArtifact,
]:
    vault, runtime, captures, store, processing = services(tmp_path)
    first = captures.create(title="First", capture_type="attachment", now=NOW)
    second = captures.create(title="Second", capture_type="attachment", now=NOW)
    return vault, runtime, captures, store, processing, first, second


def split_fixture(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    CaptureArtifactService,
    CaptureProcessingService,
    CaptureArtifact,
    tuple[tuple[str, ...], ...],
]:
    vault, runtime, captures, store, processing = services(tmp_path)
    first_source = tmp_path / "split-first.txt"
    first_source.write_text("first")
    second_source = tmp_path / "split-second.txt"
    second_source.write_text("second")
    first_ref = store.import_file(first_source, capture_source="test", now=NOW).reference
    second_ref = store.import_file(second_source, capture_source="test", now=NOW).reference
    source = captures.create(
        title="Mixed",
        capture_type="mixed",
        attachments=(first_ref, second_ref),
        now=NOW,
    )
    groups = ((first_ref.attachment_id,), (second_ref.attachment_id,))
    return vault, runtime, captures, processing, source, groups


def atomic_edit(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.external-edit")
    temporary.write_text(content)
    os.replace(temporary, path)


def transaction_artifacts(vault: Path) -> tuple[Path, ...]:
    suffixes = (
        ".staged",
        ".backup",
        ".replace-guard",
        ".replace-quarantine",
        ".replacement-rollback-quarantine",
        ".rollback-guard",
        ".rollback-quarantine",
        ".unlink-guard",
        ".unlink-quarantine",
        ".cleanup-quarantine",
    )
    return tuple(
        path
        for path in vault.rglob("*")
        if path.name.endswith(suffixes)
    )


def recovery_entries(runtime: Path) -> tuple[Path, ...]:
    root = runtime / "capture-mutations" / "recovery"
    return tuple(root.iterdir()) if root.exists() else ()


def test_merge_preview_is_bound_and_duplicate_sources_are_rejected(tmp_path: Path) -> None:
    _, _, _, _, processing, first, second = source_pair(tmp_path)
    with pytest.raises(CaptureError) as duplicate:
        processing.merge_preview((first.path, first.path))
    assert duplicate.value.code == "invalid_merge"

    preview = processing.merge_preview((first.path, second.path))
    assert preview.fingerprint.startswith("sha256:")
    with pytest.raises(CaptureError) as fingerprint_tamper:
        processing.apply_merge(replace(preview, title="Unreviewed title"), now=NOW)
    assert fingerprint_tamper.value.code == "invalid_merge_preview"
    with pytest.raises(CaptureError) as legacy_tamper:
        processing.apply_merge(
            replace(preview, title="Unreviewed title", fingerprint=""), now=NOW
        )
    assert legacy_tamper.value.code == "invalid_merge_preview"


def test_merge_serializes_with_the_shared_vault_mutation_authority(tmp_path: Path) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    with acquire_pinned_recovery_store(runtime_dir=runtime, authority_root=vault):
        with pytest.raises(CaptureError) as locked:
            processing.apply_merge(preview, idempotency_key="shared-vault-lock", now=NOW)

    assert locked.value.code == "transaction_locked"


def test_merge_and_split_preserve_policy_lineage_and_human_authority(tmp_path: Path) -> None:
    vault, _, captures, store, processing = services(tmp_path)
    first_source = tmp_path / "first.txt"
    first_source.write_text("first")
    second_source = tmp_path / "second.txt"
    second_source.write_text("second")
    first_ref = store.import_file(first_source, capture_source="test", now=NOW).reference
    second_ref = store.import_file(second_source, capture_source="test", now=NOW).reference
    first = captures.create(
        title="First",
        capture_type="attachment",
        privacy_scope="protected",
        tags=("first",),
        attachments=(first_ref,),
        exclude_from_semantic=True,
        exclude_from_reviews=True,
        now=NOW,
    )
    second = captures.create(
        title="Second",
        capture_type="attachment",
        privacy_scope="private",
        sensitive=True,
        tags=("second",),
        attachments=(second_ref,),
        exclude_from_conversations=True,
        exclude_from_experiments=True,
        now=NOW,
    )
    first_path = vault / first.path
    second_path = vault / second.path
    first_path.write_text(first_path.read_text().replace("## User annotations", "## User annotations\n\nAlpha"))
    second_path.write_text(
        second_path.read_text().replace("## User annotations", "## User annotations\n\nBeta")
    )
    first = captures.load(first.path)
    second = captures.load(second.path)

    merged = processing.apply_merge(
        processing.merge_preview((first.path, second.path)),
        idempotency_key="merge-policy",
        now=NOW,
    )
    metadata = merged.metadata
    assert metadata.privacy_scope == "protected"
    assert metadata.sensitive
    assert metadata.tags == ("first", "second")
    assert metadata.exclude_from_semantic
    assert metadata.exclude_from_conversations
    assert metadata.exclude_from_reviews
    assert metadata.exclude_from_experiments
    assert metadata.merged_from == (first.metadata.capture_id, second.metadata.capture_id)
    assert "Alpha" in merged.human_body and "Beta" in merged.human_body
    assert captures.load(first.path).human_body == first.human_body
    assert captures.load(second.path).human_body == second.human_body

    parts = processing.split(
        merged.path,
        ((first_ref.attachment_id,), (second_ref.attachment_id,)),
        expected_hash=merged.content_hash,
        idempotency_key="split-policy",
        now=NOW,
    )
    assert all(item.metadata.privacy_scope == "protected" for item in parts)
    assert all(item.metadata.sensitive for item in parts)
    assert all(item.metadata.exclude_from_semantic for item in parts)
    assert all(item.metadata.exclude_from_conversations for item in parts)
    assert all(item.metadata.exclude_from_reviews for item in parts)
    assert all(item.metadata.exclude_from_experiments for item in parts)
    assert all(item.metadata.split_from == merged.metadata.capture_id for item in parts)
    assert all("Merged source annotations" not in item.human_body for item in parts)
    assert captures.load(merged.path).human_body == merged.human_body
    assert transaction_artifacts(vault) == ()


@pytest.mark.parametrize(
    "groups",
    (
        (),
        (("first",),),
        (("first",), ()),
        (("first",), ("first",)),
        (("first",), ("unknown",)),
    ),
)
def test_split_rejects_lossy_or_ambiguous_groups_before_writing(
    tmp_path: Path, groups: tuple[tuple[str, ...], ...]
) -> None:
    _, _, captures, store, processing = services(tmp_path)
    first_source = tmp_path / "first.txt"
    first_source.write_text("first")
    second_source = tmp_path / "second.txt"
    second_source.write_text("second")
    first_ref = store.import_file(first_source, capture_source="test", now=NOW).reference
    second_ref = store.import_file(second_source, capture_source="test", now=NOW).reference
    source = captures.create(
        title="Mixed",
        capture_type="mixed",
        attachments=(first_ref, second_ref),
        now=NOW,
    )
    normalized = tuple(
        tuple(
            first_ref.attachment_id if item == "first" else item
            for item in group
        )
        for group in groups
    )

    with pytest.raises(CaptureError) as invalid:
        processing.split(source.path, normalized, expected_hash=source.content_hash, now=NOW)

    assert invalid.value.code == "invalid_split"
    assert captures.load(source.path).content_hash == source.content_hash
    assert len(captures.list()) == 1


def test_unarchivable_sources_fail_before_merge_or_split_outputs(tmp_path: Path) -> None:
    _, _, captures, store, processing = services(tmp_path)
    attachment_source = tmp_path / "attachment.txt"
    attachment_source.write_text("attachment")
    first_ref = store.import_file(attachment_source, capture_source="test", now=NOW).reference
    second_source = tmp_path / "second.txt"
    second_source.write_text("second")
    second_ref = store.import_file(second_source, capture_source="test", now=NOW).reference
    first = captures.create(
        title="Processing", capture_type="mixed", attachments=(first_ref, second_ref), now=NOW
    )
    first = captures.transition(
        first.path, "processing", expected_hash=first.content_hash, now=NOW
    )
    second = captures.create(title="Other", capture_type="attachment", now=NOW)
    preview = processing.merge_preview((first.path, second.path))
    with pytest.raises(CaptureError) as merge_error:
        processing.apply_merge(preview, now=NOW)
    assert merge_error.value.code == "invalid_transition"
    with pytest.raises(CaptureError) as split_error:
        processing.split(
            first.path,
            ((first_ref.attachment_id,), (second_ref.attachment_id,)),
            expected_hash=first.content_hash,
            now=NOW,
        )
    assert split_error.value.code == "invalid_transition"
    assert len(captures.list()) == 2


@pytest.mark.parametrize("publish_index", (0, 1, 2))
def test_handled_merge_failure_rolls_back_every_published_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publish_index: int
) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    original = {item.path: (vault / item.path).read_bytes() for item in (first, second)}

    def checkpoint(name: str) -> None:
        if name == f"after_publish:{publish_index}":
            raise RuntimeError("injected commit failure")

    monkeypatch.setattr("lifeos.captures.transaction._capture_transaction_checkpoint", checkpoint)
    with pytest.raises(CaptureError) as failed:
        processing.apply_merge(preview, idempotency_key=f"handled-{publish_index}", now=NOW)

    assert failed.value.code == "transaction_failed"
    assert {item.path for item in captures.list()} == {first.path, second.path}
    assert all((vault / path).read_bytes() == content for path, content in original.items())
    assert transaction_artifacts(vault) == ()
    assert recovery_entries(runtime) == ()


@pytest.mark.parametrize(
    "checkpoint_name",
    (
        "after_journal_initialized",
        "after_prepared",
        "after_publish:0",
        "after_publish:1",
        "after_publish:2",
        "after_committed",
    ),
)
def test_interrupted_merge_recovers_then_retries_idempotently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint_name: str
) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash(name: str) -> None:
        if name == checkpoint_name:
            raise SystemExit("simulated process interruption")

    monkeypatch.setattr("lifeos.captures.transaction._capture_transaction_checkpoint", crash)
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="recoverable-merge", now=NOW)
    assert recovery_entries(runtime)

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", lambda _name: None
    )
    merged = processing.apply_merge(
        preview, idempotency_key="recoverable-merge", now=NOW
    )
    retried = processing.apply_merge(
        preview, idempotency_key="recoverable-merge", now=NOW
    )
    assert retried.path == merged.path
    assert len(captures.list()) == 3
    assert captures.load(first.path).metadata.state == "archived"
    assert captures.load(second.path).metadata.state == "archived"
    assert transaction_artifacts(vault) == ()
    assert recovery_entries(runtime) == ()


def test_source_edit_after_preparation_is_preserved_and_no_output_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    edited = (vault / first.path).read_text() + "\nUser edit during merge.\n"

    def edit_source(name: str) -> None:
        if name == "after_prepared":
            atomic_edit(vault / first.path, edited)

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", edit_source
    )
    with pytest.raises(CaptureError) as stale:
        processing.apply_merge(preview, idempotency_key="racing-edit", now=NOW)

    assert stale.value.code == "stale_merge"
    assert (vault / first.path).read_text() == edited
    assert captures.load(second.path).metadata.state == "captured"
    assert {item.path for item in captures.list()} == {first.path, second.path}
    assert transaction_artifacts(vault) == ()
    assert recovery_entries(runtime) == ()


def test_split_source_edit_after_preparation_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, captures, processing, source, groups = split_fixture(tmp_path)
    edited = (vault / source.path).read_text() + "\nUser edit during split.\n"

    def edit_source(name: str) -> None:
        if name == "after_prepared":
            atomic_edit(vault / source.path, edited)

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", edit_source
    )
    with pytest.raises(CaptureError) as stale:
        processing.split(
            source.path,
            groups,
            expected_hash=source.content_hash,
            idempotency_key="split-racing-edit",
            now=NOW,
        )

    assert stale.value.code == "stale_split"
    assert (vault / source.path).read_text() == edited
    assert len(captures.list()) == 1
    assert transaction_artifacts(vault) == ()
    assert recovery_entries(runtime) == ()


@pytest.mark.parametrize("publish_index", (0, 1, 2))
def test_handled_split_failure_rolls_back_all_parts_and_source_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publish_index: int
) -> None:
    vault, runtime, captures, processing, source, groups = split_fixture(tmp_path)
    original = (vault / source.path).read_bytes()

    def checkpoint(name: str) -> None:
        if name == f"after_publish:{publish_index}":
            raise RuntimeError("injected split failure")

    monkeypatch.setattr("lifeos.captures.transaction._capture_transaction_checkpoint", checkpoint)
    with pytest.raises(CaptureError) as failed:
        processing.split(
            source.path,
            groups,
            expected_hash=source.content_hash,
            idempotency_key=f"split-failure-{publish_index}",
            now=NOW,
        )

    assert failed.value.code == "transaction_failed"
    assert {item.path for item in captures.list()} == {source.path}
    assert (vault / source.path).read_bytes() == original
    assert transaction_artifacts(vault) == ()
    assert recovery_entries(runtime) == ()


def test_split_retry_returns_same_parts_without_duplicate_lineage(tmp_path: Path) -> None:
    _, runtime, captures, processing, source, groups = split_fixture(tmp_path)
    parts = processing.split(
        source.path,
        groups,
        expected_hash=source.content_hash,
        idempotency_key="stable-split",
        now=NOW,
    )
    lifecycle_length = len(captures.load(source.path).metadata.lifecycle)
    updated_first = captures.save(
        parts[0],
        replace(parts[0].metadata, attachments=()),
        expected_hash=parts[0].content_hash,
    )
    shutil.rmtree(runtime / "capture-mutations" / "results")

    retried = processing.split(
        source.path,
        groups,
        expected_hash=source.content_hash,
        idempotency_key="stable-split",
        now=NOW,
    )

    assert tuple(item.path for item in retried) == tuple(item.path for item in parts)
    assert retried[0].content_hash == updated_first.content_hash
    assert len(captures.list()) == 3
    assert len(captures.load(source.path).metadata.lifecycle) == lifecycle_length


def test_foreign_edit_after_partial_publish_is_preserved_and_blocks_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    edited = (vault / first.path).read_text() + "\nExternal edit after archive publication.\n"

    def edit_after_archive(name: str) -> None:
        if name == "after_publish:1":
            atomic_edit(vault / first.path, edited)
            raise RuntimeError("force rollback")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", edit_after_archive
    )
    with pytest.raises(CaptureError) as blocked:
        processing.apply_merge(preview, idempotency_key="foreign-edit", now=NOW)

    assert blocked.value.code == "recovery_required"
    assert (vault / first.path).read_text() == edited
    assert recovery_entries(runtime)
    with pytest.raises(CaptureTransactionError) as still_blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)
    assert still_blocked.value.code == "recovery_required"


def test_idempotency_survives_disposable_result_cache_and_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    _, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    merged = processing.apply_merge(preview, idempotency_key="stable-key", now=NOW)
    lifecycle_lengths = {
        first.path: len(captures.load(first.path).metadata.lifecycle),
        second.path: len(captures.load(second.path).metadata.lifecycle),
    }
    shutil.rmtree(runtime / "capture-mutations" / "results")
    retried = processing.apply_merge(preview, idempotency_key="stable-key", now=NOW)
    assert retried.path == merged.path
    assert len(captures.list()) == 3
    assert all(
        len(captures.load(path).metadata.lifecycle) == length
        for path, length in lifecycle_lengths.items()
    )

    third = captures.create(title="Third", capture_type="attachment", now=NOW)
    fourth = captures.create(title="Fourth", capture_type="attachment", now=NOW)
    conflicting_preview = processing.merge_preview((third.path, fourth.path))
    with pytest.raises(CaptureError) as conflict:
        processing.apply_merge(
            conflicting_preview, idempotency_key="stable-key", now=NOW
        )
    assert conflict.value.code == "idempotency_conflict"
    assert captures.load(third.path).metadata.state == "captured"
    assert captures.load(fourth.path).metadata.state == "captured"


def test_deleted_merge_result_does_not_release_its_canonical_key(tmp_path: Path) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    key = "consumed-merge-key"
    merged = processing.apply_merge(
        processing.merge_preview((first.path, second.path)),
        idempotency_key=key,
        now=NOW,
    )
    (vault / merged.path).unlink()
    shutil.rmtree(runtime / "capture-mutations" / "results")
    third = captures.create(title="Third", capture_type="attachment", now=NOW)
    fourth = captures.create(title="Fourth", capture_type="attachment", now=NOW)

    with pytest.raises(CaptureError) as conflict:
        processing.apply_merge(
            processing.merge_preview((third.path, fourth.path)),
            idempotency_key=key,
            now=NOW,
        )

    assert conflict.value.code == "idempotency_conflict"
    assert captures.load(third.path).metadata.state == "captured"
    assert captures.load(fourth.path).metadata.state == "captured"


def test_deleted_split_results_leave_canonical_recovery_evidence(tmp_path: Path) -> None:
    vault, runtime, _, processing, source, groups = split_fixture(tmp_path)
    key = "missing-split-results"
    parts = processing.split(
        source.path,
        groups,
        expected_hash=source.content_hash,
        idempotency_key=key,
        now=NOW,
    )
    for part in parts:
        (vault / part.path).unlink()
    shutil.rmtree(runtime / "capture-mutations" / "results")

    with pytest.raises(CaptureError) as incomplete:
        processing.split(
            source.path,
            groups,
            expected_hash=source.content_hash,
            idempotency_key=key,
            now=NOW,
        )

    assert incomplete.value.code == "recovery_required"


def test_capture_runtime_rebuild_does_not_erase_active_transaction_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave recovery state")

    monkeypatch.setattr("lifeos.captures.transaction._capture_transaction_checkpoint", crash)
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="active-evidence", now=NOW)
    before = recovery_entries(runtime)
    assert before
    (runtime / "captures").mkdir(parents=True, exist_ok=True)
    (runtime / "captures" / "junk.json").write_text("{}")

    audit_capture_recovery(vault_root=vault, runtime_dir=runtime, delete_runtime=True)

    assert recovery_entries(runtime) == before


def test_tampered_recovery_journal_cannot_select_an_external_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave recovery state")

    monkeypatch.setattr("lifeos.captures.transaction._capture_transaction_checkpoint", crash)
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="tampered-journal", now=NOW)
    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    sentinel = tmp_path / "sentinel.md"
    sentinel.write_text("must remain")
    journal["operations"][0]["path"] = "captures/../../sentinel.md"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)
    assert blocked.value.code == "recovery_required"
    assert sentinel.read_text() == "must remain"


def test_tampered_committed_phase_cannot_accept_a_partial_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_output(name: str) -> None:
        if name == "after_publish:0":
            raise SystemExit("leave one published output")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_output
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="phase-flip", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["phase"] = "committed"
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert captures.load(first.path).metadata.state == "captured"
    assert captures.load(second.path).metadata.state == "captured"
    assert recovery_entries(runtime)


def test_tampered_journal_cannot_omit_a_planned_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_prepare(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave prepared operation set")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_prepare
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="operation-omission", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["operations"].pop()
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert recovery_entries(runtime)


@pytest.mark.parametrize("matching_declared_hash", (True, False))
def test_forged_receipt_cannot_short_circuit_a_merge(
    tmp_path: Path, matching_declared_hash: bool
) -> None:
    _, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    key = "forged-receipt"
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    results = runtime / "capture-mutations" / "results"
    results.mkdir(parents=True)
    (results / f"{key_hash}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation": "merge",
                "idempotency_key_hash": key_hash if matching_declared_hash else "f" * 64,
                "request_fingerprint": preview.fingerprint,
                "result_paths": [first.path],
            }
        )
    )

    with pytest.raises(CaptureError) as blocked:
        processing.apply_merge(preview, idempotency_key=key, now=NOW)

    assert blocked.value.code == "recovery_required"
    assert captures.load(first.path).metadata.state == "captured"
    assert captures.load(second.path).metadata.state == "captured"
    assert len(captures.list()) == 2


def test_forged_merge_marker_requires_complete_canonical_lineage(tmp_path: Path) -> None:
    _, _, captures, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    key = "forged-merge-marker"
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    captures.create(
        title="Forged merge result",
        capture_type="attachment",
        source_entry_point=(
            "capture-mutation:merge:"
            f"{key_hash}:{preview.fingerprint.removeprefix('sha256:')}:1:1"
        ),
        now=NOW,
    )

    with pytest.raises(CaptureError) as blocked:
        processing.apply_merge(preview, idempotency_key=key, now=NOW)

    assert blocked.value.code == "recovery_required"
    assert captures.load(first.path).metadata.state == "captured"
    assert captures.load(second.path).metadata.state == "captured"


def test_forged_split_markers_require_complete_canonical_lineage(tmp_path: Path) -> None:
    _, _, captures, processing, source, groups = split_fixture(tmp_path)
    key = "forged-split-marker"
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    request = {
        "source_path": source.path,
        "source_hash": source.content_hash,
        "groups": [list(group) for group in groups],
    }
    payload = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    request_fingerprint = hashlib.sha256(payload).hexdigest()
    for index in (1, 2):
        captures.create(
            title=f"Forged split result {index}",
            capture_type="attachment",
            source_entry_point=(
                "capture-mutation:split:"
                f"{key_hash}:{request_fingerprint}:{index}:2"
            ),
            now=NOW,
        )

    with pytest.raises(CaptureError) as blocked:
        processing.split(
            source.path,
            groups,
            expected_hash=source.content_hash,
            idempotency_key=key,
            now=NOW,
        )

    assert blocked.value.code == "recovery_required"
    assert captures.load(source.path).metadata.state == "captured"


def test_byte_identical_atomic_replacement_blocks_committed_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_commit(name: str) -> None:
        if name == "after_committed":
            raise SystemExit("leave committed recovery state")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_commit
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="identical-replacement", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal = json.loads((transaction_dir / "journal.json").read_text())
    target = vault / journal["result_paths"][0]
    original_inode = target.stat().st_ino
    original_content = target.read_text()
    atomic_edit(target, original_content)
    assert target.stat().st_ino != original_inode

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert target.read_text() == original_content
    assert recovery_entries(runtime) == (transaction_dir,)


def test_missing_staging_proof_blocks_committed_recovery_and_retains_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_commit(name: str) -> None:
        if name == "after_committed":
            raise SystemExit("leave committed recovery state")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_commit
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="missing-staging", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal = json.loads((transaction_dir / "journal.json").read_text())
    operation = journal["operations"][0]
    target = Path(operation["path"])
    staging = (
        vault
        / target.parent
        / f".{target.name}.{operation['artifact_token']}.staged"
    )
    staging.unlink()

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert not staging.exists()
    assert recovery_entries(runtime) == (transaction_dir,)


@pytest.mark.parametrize("suffix", ("replace-guard", "replace-quarantine"))
def test_unexpected_reserved_mutation_artifact_blocks_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_prepare(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave prepared recovery state")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_prepare
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(
            preview, idempotency_key=f"unexpected-{suffix}", now=NOW
        )

    transaction_dir = recovery_entries(runtime)[0]
    journal = json.loads((transaction_dir / "journal.json").read_text())
    operation = journal["operations"][0]
    target = Path(operation["path"])
    unexpected = vault / target.parent / f".{target.name}.{'a' * 32}.{suffix}"
    unexpected.write_text("foreign transaction artifact")

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert unexpected.exists()
    assert recovery_entries(runtime) == (transaction_dir,)


@pytest.mark.parametrize("field", ("operation", "phase", "kind"))
def test_unhashable_journal_enum_types_fail_as_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_prepare(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave prepared recovery state")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_prepare
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key=f"unhashable-{field}", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    if field == "kind":
        journal["operations"][0]["kind"] = []
    else:
        journal[field] = [] if field == "operation" else {}
    journal_path.write_text(json.dumps(journal))

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert recovery_entries(runtime) == (transaction_dir,)


def test_recomputed_three_source_omission_cannot_rebind_canonical_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, runtime, captures, _, processing, first, second = source_pair(tmp_path)
    third = captures.create(title="Third", capture_type="attachment", now=NOW)
    preview = processing.merge_preview((first.path, second.path, third.path))

    def crash_after_prepare(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave prepared three-source plan")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_prepare
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(preview, idempotency_key="recomputed-omission", now=NOW)

    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["operations"].pop()
    intent_payload = {
        "schema_version": journal["schema_version"],
        "operation": journal["operation"],
        "idempotency_key_hash": journal["idempotency_key_hash"],
        "request_fingerprint": journal["request_fingerprint"],
        "result_paths": journal["result_paths"],
        "vault_dev": journal["vault_dev"],
        "vault_ino": journal["vault_ino"],
        "operations": [
            {key: value for key, value in operation.items() if key != "artifact_token"}
            for operation in journal["operations"]
        ],
    }
    serialized = (
        json.dumps(intent_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    intent_hash = hashlib.sha256(serialized).hexdigest()
    journal["intent_hash"] = intent_hash
    journal["transaction_id"] = f"ctx-{intent_hash[:32]}"
    for index, operation in enumerate(journal["operations"]):
        token_payload = (
            f"capture-transaction-artifact-v1\0{intent_hash}\0{index}\0{operation['path']}"
        ).encode("utf-8")
        operation["artifact_token"] = hashlib.sha256(token_payload).hexdigest()[:32]
    journal_path.write_text(json.dumps(journal))
    rebound_dir = transaction_dir.with_name(journal["transaction_id"])
    transaction_dir.rename(rebound_dir)

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert captures.load(first.path).metadata.state == "captured"
    assert captures.load(second.path).metadata.state == "captured"
    assert captures.load(third.path).metadata.state == "captured"
    assert recovery_entries(runtime) == (rebound_dir,)


def test_low_level_receipt_retry_cannot_omit_source_writes(tmp_path: Path) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    key = "incomplete-low-level-retry"
    merged = processing.apply_merge(preview, idempotency_key=key, now=NOW)

    with pytest.raises(CaptureTransactionError) as blocked:
        execute_capture_transaction(
            vault_root=vault,
            runtime_dir=runtime,
            operation="merge",
            idempotency_key=key,
            request_fingerprint=preview.fingerprint,
            result_paths=(merged.path,),
            writes=(CaptureFileWrite(merged.path, (vault / merged.path).read_bytes()),),
        )

    assert blocked.value.code == "recovery_required"


def malformed_json_fragment(kind: str) -> str:
    if kind == "oversized-integer":
        return "9" * 5_000
    return "[" * 1_200 + "0" + "]" * 1_200


@pytest.mark.parametrize("malformed_kind", ("oversized-integer", "excessive-nesting"))
def test_malformed_journal_json_limits_fail_as_recovery_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed_kind: str
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))

    def crash_after_prepare(name: str) -> None:
        if name == "after_prepared":
            raise SystemExit("leave journal for parser hardening")

    monkeypatch.setattr(
        "lifeos.captures.transaction._capture_transaction_checkpoint", crash_after_prepare
    )
    with pytest.raises(SystemExit):
        processing.apply_merge(
            preview, idempotency_key=f"journal-{malformed_kind}", now=NOW
        )

    transaction_dir = recovery_entries(runtime)[0]
    journal_path = transaction_dir / "journal.json"
    journal = json.loads(journal_path.read_text())
    journal["vault_dev"] = "MALFORMED_VALUE"
    payload = json.dumps(journal).replace(
        '"MALFORMED_VALUE"', malformed_json_fragment(malformed_kind)
    )
    journal_path.write_text(payload)

    with pytest.raises(CaptureTransactionError) as blocked:
        recover_capture_transactions(vault_root=vault, runtime_dir=runtime)

    assert blocked.value.code == "recovery_required"
    assert recovery_entries(runtime) == (transaction_dir,)


@pytest.mark.parametrize("malformed_kind", ("oversized-integer", "excessive-nesting"))
def test_malformed_receipt_json_limits_fail_as_recovery_required(
    tmp_path: Path, malformed_kind: str
) -> None:
    vault, runtime, _, _, processing, first, second = source_pair(tmp_path)
    preview = processing.merge_preview((first.path, second.path))
    key = f"receipt-{malformed_kind}"
    merged = processing.apply_merge(preview, idempotency_key=key, now=NOW)
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    receipt_path = runtime / "capture-mutations" / "results" / f"{key_hash}.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["schema_version"] = "MALFORMED_VALUE"
    payload = json.dumps(receipt).replace(
        '"MALFORMED_VALUE"', malformed_json_fragment(malformed_kind)
    )
    receipt_path.write_text(payload)

    with pytest.raises(CaptureTransactionError) as blocked:
        execute_capture_transaction(
            vault_root=vault,
            runtime_dir=runtime,
            operation="merge",
            idempotency_key=key,
            request_fingerprint=preview.fingerprint,
            result_paths=(merged.path,),
            writes=(CaptureFileWrite(merged.path, (vault / merged.path).read_bytes()),),
        )

    assert blocked.value.code == "recovery_required"
