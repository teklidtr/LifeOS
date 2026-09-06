"""Deterministic diagnostics and proposal-only orphan ownership remediation."""

from __future__ import annotations

import os
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lifeos.proposals.publication import (
    ProposalDocuments,
    ProposalPublicationError,
    publish_proposal_documents,
)
from lifeos.proposals.lifecycle import serialize_proposal_markdown
from lifeos.proposals.patches import (
    PatchDocumentV2,
    ReleaseGeneratedOwnershipV2,
    serialize_patch_json_bytes,
)
from lifeos.proposals.schema import (
    ProposalMetadata,
    ProposalRisk,
    ProposalStatus,
    generate_proposal_id,
)
from lifeos.proposals.review_snapshot import build_review_snapshot_bytes_from_patches

from .manifest import DEFAULT_OWNERSHIP_MANIFEST_PATH, GeneratedOwnership, ManifestEntry


class OwnershipReconciliationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrphanedGeneratedOwnership:
    target_path: str
    content_hash: str
    generator_id: str
    generator_version: str
    created_at: str
    updated_at: str
    diagnostic_code: str = "owned_target_missing"
    diagnostic: str = "Generated ownership remains canonical, but its target is absent."
    restore_instructions: str = (
        "Restore reviewed bytes at the target path whose SHA-256 matches content_hash, "
        "then refresh. LifeOS will retain the existing ownership entry."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OwnershipReleaseProposalResult:
    proposal_id: str
    target_path: str
    proposal_path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _target_is_absent(vault_root: Path, target_path: str) -> bool:
    current = vault_root
    for component in Path(target_path).parts:
        current = current / component
        try:
            os.stat(current, follow_symlinks=False)
        except FileNotFoundError:
            return True
        except OSError:
            return False
    return False


def list_orphaned_generated_ownership(
    vault_root: Path,
) -> tuple[OrphanedGeneratedOwnership, ...]:
    manifest_path = vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH
    ownership = GeneratedOwnership.load(manifest_path, vault_root)
    orphans = []
    for target_path, entry in sorted(ownership.entries.items()):
        if not _target_is_absent(vault_root, target_path):
            continue
        orphans.append(_orphan(target_path, entry))
    return tuple(orphans)


def create_ownership_release_proposal(
    *,
    vault_root: Path,
    target_path: str,
    created_by: str,
    now: datetime | None = None,
) -> OwnershipReleaseProposalResult:
    orphan = next(
        (
            item
            for item in list_orphaned_generated_ownership(vault_root)
            if item.target_path == target_path
        ),
        None,
    )
    if orphan is None:
        raise OwnershipReconciliationError(
            "Ownership release requires a currently missing generated target"
        )

    created = now or datetime.now(timezone.utc)
    if created.tzinfo is None or created.utcoffset() != timedelta(0):
        raise OwnershipReconciliationError("now must be a timezone-aware UTC datetime")
    proposal_id = generate_proposal_id(lambda: created, lambda: secrets.token_hex(4))
    created_at = created.strftime("%Y-%m-%dT%H:%M:%SZ")
    operation = ReleaseGeneratedOwnershipV2(
        id="op-release-generated-ownership",
        target_path=orphan.target_path,
        expected_content_hash=f"sha256:{orphan.content_hash}",
        expected_generator_id=orphan.generator_id,
        expected_generator_version=orphan.generator_version,
        expected_created_at=orphan.created_at,
        expected_updated_at=orphan.updated_at,
    )
    document = PatchDocumentV2(2, proposal_id, (operation,))
    metadata = ProposalMetadata(
        id=proposal_id,
        schema_version=1,
        patch_schema_version=2,
        lifecycle_schema_version=1,
        title=f"Release generated ownership: {orphan.target_path}",
        description="Explicitly release an orphaned durable ownership entry",
        status=ProposalStatus.DRAFT,
        risk=ProposalRisk.HIGH,
        created_at=created_at,
        created_by=created_by,
        submitted_at=None,
        submitted_by=None,
        review_digest=None,
        approved_at=None,
        approved_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
        applied_at=None,
        applied_by=None,
        related_goals=(),
        related_sources=(str(DEFAULT_OWNERSHIP_MANIFEST_PATH),),
        extensions={
            "ownership_reconciliation": {
                "target_path": orphan.target_path,
                "diagnostic_code": orphan.diagnostic_code,
            }
        },
    )
    body = (
        f"Releases the durable generated ownership entry for `{orphan.target_path}`.\n\n"
        f"- Recorded SHA-256: `{orphan.content_hash}`\n"
        f"- Generator: `{orphan.generator_id}` `{orphan.generator_version}`\n"
        f"- Created: `{orphan.created_at}`\n"
        f"- Updated: `{orphan.updated_at}`\n\n"
        "The target must remain absent and every recorded field must still match when "
        "this proposal is applied. This does not delete or recreate target content."
    )
    proposal_markdown = serialize_proposal_markdown(metadata, body).replace(
        b"\nreview_digest: null\n", b"\n"
    )
    patches_json = serialize_patch_json_bytes(document)
    proposal_path = _publish_proposal(
        vault_root=vault_root,
        proposal_id=proposal_id,
        proposal_markdown=proposal_markdown,
        patches_json=patches_json,
    )
    return OwnershipReleaseProposalResult(
        proposal_id=proposal_id,
        target_path=orphan.target_path,
        proposal_path=proposal_path.relative_to(vault_root).as_posix(),
    )


def _orphan(target_path: str, entry: ManifestEntry) -> OrphanedGeneratedOwnership:
    return OrphanedGeneratedOwnership(
        target_path=target_path,
        content_hash=entry.content_hash,
        generator_id=entry.generator_id,
        generator_version=entry.generator_version,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _publish_proposal(
    *,
    vault_root: Path,
    proposal_id: str,
    proposal_markdown: bytes,
    patches_json: bytes,
) -> Path:
    review_json = build_review_snapshot_bytes_from_patches(
        vault_root=vault_root,
        patches_json=patches_json,
    )
    try:
        publish_proposal_documents(
            vault_root=vault_root,
            proposal_id=proposal_id,
            documents=ProposalDocuments(proposal_markdown, patches_json, review_json),
        )
    except ProposalPublicationError as error:
        raise OwnershipReconciliationError(
            f"Could not publish ownership release proposal: {error}"
        ) from error
    return vault_root / "proposals" / proposal_id
