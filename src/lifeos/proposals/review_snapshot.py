"""Immutable, canonical proposal review diffs."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from lifeos._secure_io import open_directory_secure, read_file_secure
from lifeos.markdown.parser import parse_markdown_note
from .patches import (
    AnyPatchDocument,
    PatchOperation,
    serialize_patch_json_bytes,
    validate_patch_document,
)

REVIEW_SNAPSHOT_FILENAME = "review.json"
REVIEW_SNAPSHOT_SCHEMA_VERSION = 1
_OWNERSHIP_MANIFEST_PATH = PurePosixPath("system/generated-ownership.json")


def _reject_duplicates(ordered_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in ordered_pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(constant: str) -> float:
    raise ValueError(f"nonstandard constant not allowed: {constant}")


class ReviewSnapshotError(ValueError):
    def __init__(self, code: str, field_path: str, message: str) -> None:
        super().__init__(f"{field_path} ({code}): {message}")
        self.code = code
        self.field_path = field_path
        self.message = message


@dataclass(frozen=True, slots=True)
class OperationReviewSnapshot:
    operation_id: str
    operation_type: str
    target_path: str
    unified_diff: str


@dataclass(frozen=True, slots=True)
class ProposalReviewSnapshot:
    schema_version: int
    proposal_id: str
    patches_hash: str
    operations: tuple[OperationReviewSnapshot, ...]


def _prefixed_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _unified_diff(
    original: str,
    candidate: str,
    target_path: str,
    *,
    created: bool = False,
) -> str:
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            candidate.splitlines(),
            fromfile="/dev/null" if created else f"a/{target_path}",
            tofile=f"b/{target_path}",
            lineterm="",
        )
    )


def _read_target_text(vault_root: Path, target_path: str) -> tuple[str, bytes]:
    root_fd = open_directory_secure(vault_root)
    try:
        content = read_file_secure(target_path, vault_root, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    return content.decode("utf-8"), content


def operation_unified_diff(vault_root: Path, operation: PatchOperation) -> str:
    target_path = operation.target_path
    if operation.op == "patch_human_file":
        return "\n".join(
            (
                f"--- a/{target_path}",
                f"+++ b/{target_path}",
                operation.unified_diff.rstrip("\n"),
            )
        )
    if operation.op in ("create_file", "create_generated_file"):
        return _unified_diff("", operation.new_content, target_path, created=True)
    if operation.op == "release_generated_ownership":
        from lifeos.ownership.manifest import (
            GeneratedOwnership,
            serialize_generated_ownership_bytes,
        )

        ownership = GeneratedOwnership.load(
            vault_root / _OWNERSHIP_MANIFEST_PATH,
            vault_root,
        )
        entry = ownership.entries.get(target_path)
        if entry is None:
            raise ReviewSnapshotError(
                "ownership_entry_missing",
                target_path,
                "ownership entry no longer exists",
            )
        reviewed_entry = (
            operation.expected_content_hash,
            operation.expected_generator_id,
            operation.expected_generator_version,
            operation.expected_created_at,
            operation.expected_updated_at,
        )
        current_entry = (
            f"sha256:{entry.content_hash}",
            entry.generator_id,
            entry.generator_version,
            entry.created_at,
            entry.updated_at,
        )
        if reviewed_entry != current_entry:
            raise ReviewSnapshotError(
                "ownership_entry_changed",
                target_path,
                "ownership entry no longer matches the operation",
            )
        candidate_entries = dict(ownership.entries)
        del candidate_entries[target_path]
        original = serialize_generated_ownership_bytes(ownership.entries).decode("utf-8")
        candidate = serialize_generated_ownership_bytes(candidate_entries).decode("utf-8")
        return _unified_diff(
            original,
            candidate,
            str(_OWNERSHIP_MANIFEST_PATH),
        )

    original, original_bytes = _read_target_text(vault_root, target_path)
    expected_hash = getattr(operation, "base_hash", "")
    if _prefixed_hash(original_bytes) != expected_hash:
        raise ReviewSnapshotError(
            "stale_base_hash",
            target_path,
            "target content no longer matches the operation base hash",
        )
    if operation.op == "replace_generated_file":
        candidate = operation.new_content
    elif operation.op == "replace_managed_block":
        parsed = parse_markdown_note(vault_root / target_path, content=original)
        matching_blocks = [
            block for block in parsed.managed_blocks if block.name == operation.block_name
        ]
        if len(matching_blocks) != 1:
            raise ReviewSnapshotError(
                "managed_block_mismatch",
                target_path,
                f"managed block '{operation.block_name}' is not present exactly once",
            )
        target_block = matching_blocks[0]
        lines = original.splitlines(keepends=True)
        before = "".join(lines[: target_block.start_line])
        after = "".join(lines[target_block.end_line - 1 :])
        candidate = before + operation.new_content + after
    else:
        raise ReviewSnapshotError(
            "unsupported_operation",
            target_path,
            f"unsupported operation type '{operation.op}'",
        )
    return _unified_diff(original, candidate, target_path)


def build_review_snapshot(
    *,
    vault_root: Path,
    patch_document: AnyPatchDocument,
) -> ProposalReviewSnapshot:
    patches_bytes = serialize_patch_json_bytes(patch_document)
    operations = tuple(
        OperationReviewSnapshot(
            operation_id=operation.id,
            operation_type=operation.op,
            target_path=operation.target_path,
            unified_diff=operation_unified_diff(vault_root, operation),
        )
        for operation in patch_document.operations
    )
    return ProposalReviewSnapshot(
        schema_version=REVIEW_SNAPSHOT_SCHEMA_VERSION,
        proposal_id=patch_document.proposal_id,
        patches_hash=_prefixed_hash(patches_bytes),
        operations=operations,
    )


def build_review_snapshot_bytes_from_patches(
    *,
    vault_root: Path,
    patches_json: bytes,
) -> bytes:
    try:
        data = json.loads(patches_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewSnapshotError(
            "malformed_patches",
            "patches.json",
            "cannot build a review snapshot from malformed patches",
        ) from error
    document = validate_patch_document(data)
    if serialize_patch_json_bytes(document) != patches_json:
        raise ReviewSnapshotError(
            "noncanonical_patches",
            "patches.json",
            "patches must be canonical before snapshot creation",
        )
    return serialize_review_snapshot_bytes(
        build_review_snapshot(vault_root=vault_root, patch_document=document)
    )


def serialize_review_snapshot(snapshot: ProposalReviewSnapshot) -> dict[str, Any]:
    return {
        "schema_version": snapshot.schema_version,
        "proposal_id": snapshot.proposal_id,
        "patches_hash": snapshot.patches_hash,
        "operations": [
            {
                "operation_id": operation.operation_id,
                "operation_type": operation.operation_type,
                "target_path": operation.target_path,
                "unified_diff": operation.unified_diff,
            }
            for operation in snapshot.operations
        ],
    }


def serialize_review_snapshot_bytes(snapshot: ProposalReviewSnapshot) -> bytes:
    return (
        json.dumps(
            serialize_review_snapshot(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _require_exact_fields(
    data: Mapping[str, Any],
    *,
    expected: set[str],
    field_path: str,
) -> None:
    unknown = set(data) - expected
    missing = expected - set(data)
    if unknown:
        raise ReviewSnapshotError(
            "unknown_field", field_path, f"unknown fields: {sorted(unknown)}"
        )
    if missing:
        raise ReviewSnapshotError(
            "missing_field", field_path, f"missing fields: {sorted(missing)}"
        )


def validate_review_snapshot(
    data: Mapping[str, Any],
    *,
    patch_document: AnyPatchDocument,
) -> ProposalReviewSnapshot:
    if not isinstance(data, dict):
        raise ReviewSnapshotError("invalid_type", "$", "snapshot must be an object")
    _require_exact_fields(
        data,
        expected={"schema_version", "proposal_id", "patches_hash", "operations"},
        field_path="$",
    )
    if data["schema_version"] != REVIEW_SNAPSHOT_SCHEMA_VERSION:
        raise ReviewSnapshotError(
            "unsupported_version", "schema_version", "unsupported snapshot schema"
        )
    if data["proposal_id"] != patch_document.proposal_id:
        raise ReviewSnapshotError(
            "proposal_id_mismatch", "proposal_id", "snapshot proposal ID does not match"
        )
    expected_patch_hash = _prefixed_hash(serialize_patch_json_bytes(patch_document))
    if data["patches_hash"] != expected_patch_hash:
        raise ReviewSnapshotError(
            "patches_hash_mismatch", "patches_hash", "snapshot patches hash does not match"
        )
    operations_data = data["operations"]
    if not isinstance(operations_data, list):
        raise ReviewSnapshotError("invalid_type", "operations", "must be a list")
    if len(operations_data) != len(patch_document.operations):
        raise ReviewSnapshotError(
            "operation_count_mismatch", "operations", "operation count does not match"
        )
    operations = []
    for index, (operation_data, patch_operation) in enumerate(
        zip(operations_data, patch_document.operations, strict=True)
    ):
        field_path = f"operations[{index}]"
        if not isinstance(operation_data, dict):
            raise ReviewSnapshotError("invalid_type", field_path, "must be an object")
        _require_exact_fields(
            operation_data,
            expected={"operation_id", "operation_type", "target_path", "unified_diff"},
            field_path=field_path,
        )
        expected_identity = (
            patch_operation.id,
            patch_operation.op,
            patch_operation.target_path,
        )
        actual_identity = (
            operation_data["operation_id"],
            operation_data["operation_type"],
            operation_data["target_path"],
        )
        if actual_identity != expected_identity:
            raise ReviewSnapshotError(
                "operation_identity_mismatch",
                field_path,
                "snapshot operation does not match patches.json",
            )
        unified_diff = operation_data["unified_diff"]
        if not isinstance(unified_diff, str):
            raise ReviewSnapshotError(
                "invalid_type", f"{field_path}.unified_diff", "must be a string"
            )
        operations.append(
            OperationReviewSnapshot(
                operation_id=patch_operation.id,
                operation_type=patch_operation.op,
                target_path=patch_operation.target_path,
                unified_diff=unified_diff,
            )
        )
    return ProposalReviewSnapshot(
        schema_version=REVIEW_SNAPSHOT_SCHEMA_VERSION,
        proposal_id=patch_document.proposal_id,
        patches_hash=expected_patch_hash,
        operations=tuple(operations),
    )


def parse_review_snapshot_bytes(
    content: bytes,
    *,
    patch_document: AnyPatchDocument,
) -> ProposalReviewSnapshot:
    if content.startswith(b"\xef\xbb\xbf"):
        raise ReviewSnapshotError("invalid_bom", "$", "UTF-8 BOM is not allowed")
    try:
        decoded = content.decode("utf-8")
        data = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as error:
        raise ReviewSnapshotError("invalid_utf8", "$", "snapshot is not UTF-8") from error
    except (json.JSONDecodeError, ValueError) as error:
        raise ReviewSnapshotError("malformed_json", "$", str(error)) from error
    snapshot = validate_review_snapshot(data, patch_document=patch_document)
    if serialize_review_snapshot_bytes(snapshot) != content:
        raise ReviewSnapshotError(
            "noncanonical_json", "$", "snapshot bytes are not canonical"
        )
    return snapshot
