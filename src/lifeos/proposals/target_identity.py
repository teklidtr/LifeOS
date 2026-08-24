"""Review-bound stable target identity metadata for proposal replacement operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from lifeos.coherence import IdentitySnapshot, TargetResolution, assess_proposal_target
from lifeos.proposals.patches import AnyPatchDocument, PatchOperation
from lifeos.proposals.schema import ProposalMetadata, serialize_metadata

TARGET_IDENTITY_EXTENSION = "lifeos_target_identity"
TARGET_IDENTITY_SCHEMA_VERSION = 1


class ProposalTargetIdentityError(ValueError):
    """Raised when proposal target identity metadata is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class ProposalTargetIdentity:
    operation_id: str
    stable_id: str
    reviewed_path: str
    reviewed_base_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "operation_id": self.operation_id,
            "stable_id": self.stable_id,
            "reviewed_path": self.reviewed_path,
            "reviewed_base_hash": self.reviewed_base_hash,
        }


def with_target_identity_extension(
    metadata: ProposalMetadata,
    patch: AnyPatchDocument,
    snapshot: IdentitySnapshot,
) -> ProposalMetadata:
    """Attach stable identity facts for existing targets without changing patch semantics.

    Create operations remain path-oriented. Replacement operations keep their reviewed path
    and base hash exactly as-is; the extension only records the durable frontmatter ``id``
    observed for that reviewed target. Because proposal metadata participates in lifecycle
    review digests, the identity binding is review-bound rather than an unsigned side table.
    """
    targets: list[dict[str, str]] = []
    for operation in patch.operations:
        reviewed_hash = _reviewed_hash(operation)
        if reviewed_hash is None:
            continue
        note = snapshot.by_path(operation.target_path)
        if note is None or note.stable_id is None:
            continue
        matches = snapshot.by_stable_id(note.stable_id)
        if len(matches) != 1:
            paths = ", ".join(item.path for item in matches)
            raise ProposalTargetIdentityError(
                f"Operation {operation.id!r} stable id {note.stable_id!r} is ambiguous: {paths}"
            )
        if note.content_hash != reviewed_hash:
            raise ProposalTargetIdentityError(
                f"Operation {operation.id!r} base hash does not match the reviewed canonical note"
            )
        targets.append(
            ProposalTargetIdentity(
                operation_id=operation.id,
                stable_id=note.stable_id,
                reviewed_path=operation.target_path,
                reviewed_base_hash=reviewed_hash,
            ).to_dict()
        )

    if not targets:
        return metadata

    # ProposalMetadata freezes arbitrary extension mappings so callers cannot mutate
    # review-bound state in place. Reuse the schema serializer to obtain a fully thawed,
    # canonical copy before adding this extension; a shallow dict(metadata.extensions)
    # leaves nested mappingproxy values behind and PyYAML cannot serialize them.
    serialized_extensions = serialize_metadata(metadata)["extensions"]
    if not isinstance(serialized_extensions, dict):
        raise ProposalTargetIdentityError("Proposal metadata extensions did not serialize to a mapping")
    extensions = dict(serialized_extensions)
    if TARGET_IDENTITY_EXTENSION in extensions:
        raise ProposalTargetIdentityError(
            f"Proposal metadata already contains {TARGET_IDENTITY_EXTENSION!r}"
        )
    extensions[TARGET_IDENTITY_EXTENSION] = {
        "schema_version": TARGET_IDENTITY_SCHEMA_VERSION,
        "targets": targets,
    }
    return replace(metadata, extensions=extensions)


def parse_target_identities(
    metadata: ProposalMetadata,
    patch: AnyPatchDocument,
) -> tuple[ProposalTargetIdentity, ...]:
    """Parse and cross-check review-bound identity metadata against patch operations."""
    raw = metadata.extensions.get(TARGET_IDENTITY_EXTENSION)
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ProposalTargetIdentityError("Target identity extension must be a mapping")
    if set(raw) != {"schema_version", "targets"}:
        raise ProposalTargetIdentityError("Target identity extension contains unexpected fields")
    if raw.get("schema_version") != TARGET_IDENTITY_SCHEMA_VERSION:
        raise ProposalTargetIdentityError("Unsupported target identity extension schema version")
    targets = raw.get("targets")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        raise ProposalTargetIdentityError("Target identity targets must be a sequence")

    operations = {operation.id: operation for operation in patch.operations}
    seen: set[str] = set()
    parsed: list[ProposalTargetIdentity] = []
    for index, item in enumerate(targets):
        if not isinstance(item, Mapping):
            raise ProposalTargetIdentityError(f"Target identity entry {index} must be a mapping")
        if set(item) != {
            "operation_id",
            "stable_id",
            "reviewed_path",
            "reviewed_base_hash",
        }:
            raise ProposalTargetIdentityError(
                f"Target identity entry {index} contains unexpected fields"
            )
        operation_id = _required_string(item, "operation_id", index)
        stable_id = _required_string(item, "stable_id", index)
        reviewed_path = _required_string(item, "reviewed_path", index)
        reviewed_base_hash = _required_string(item, "reviewed_base_hash", index)
        if not reviewed_base_hash.startswith("sha256:") or len(reviewed_base_hash) != 71:
            raise ProposalTargetIdentityError(
                f"Target identity entry {index} has an invalid reviewed_base_hash"
            )
        if operation_id in seen:
            raise ProposalTargetIdentityError(
                f"Target identity operation {operation_id!r} is duplicated"
            )
        seen.add(operation_id)
        operation = operations.get(operation_id)
        if operation is None:
            raise ProposalTargetIdentityError(
                f"Target identity operation {operation_id!r} is not present in the patch"
            )
        operation_hash = _reviewed_hash(operation)
        if operation_hash is None:
            raise ProposalTargetIdentityError(
                f"Target identity operation {operation_id!r} is not a replacement operation"
            )
        if operation.target_path != reviewed_path or operation_hash != reviewed_base_hash:
            raise ProposalTargetIdentityError(
                f"Target identity operation {operation_id!r} does not match its reviewed patch target"
            )
        parsed.append(
            ProposalTargetIdentity(
                operation_id=operation_id,
                stable_id=stable_id,
                reviewed_path=reviewed_path,
                reviewed_base_hash=reviewed_base_hash,
            )
        )
    return tuple(parsed)


def assess_proposal_target_identities(
    metadata: ProposalMetadata,
    patch: AnyPatchDocument,
    snapshot: IdentitySnapshot,
) -> dict[str, TargetResolution]:
    """Assess every identity-bound target against the current canonical vault view."""
    return {
        target.operation_id: assess_proposal_target(
            snapshot,
            reviewed_path=target.reviewed_path,
            reviewed_base_hash=target.reviewed_base_hash,
            stable_id=target.stable_id,
            proposal_status=metadata.status.value,
        )
        for target in parse_target_identities(metadata, patch)
    }


def _reviewed_hash(operation: PatchOperation) -> str | None:
    base_hash = getattr(operation, "base_hash", None)
    if isinstance(base_hash, str):
        return base_hash
    expected_hash = getattr(operation, "expected_content_hash", None)
    return expected_hash if isinstance(expected_hash, str) else None


def _required_string(item: Mapping[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProposalTargetIdentityError(
            f"Target identity entry {index} field {key!r} must be a trimmed non-empty string"
        )
    return value
