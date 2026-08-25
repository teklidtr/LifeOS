"""Public SQLite registry interface for deterministic LifeOS state."""

import os
from collections.abc import Callable
from pathlib import Path

from lifeos.registry import file_tracking as _file_tracking
from lifeos.registry._migrations import CURRENT_SCHEMA_VERSION
from lifeos.registry._registry import (
    Registry,
    RegistryError,
    RegistryHistoryError,
    RegistryMigrationError,
    RegistryOpenError,
    UnsupportedSchemaVersionError,
)
from lifeos.registry.file_tracking import (
    FileComparison,
    FileRegistrationState,
    FileTrackingError,
    RegisteredStableIdentity,
    ScanResult,
    compare_registered_file,
    hash_file_content,
    list_registered_stable_identities,
    resolve_registered_stable_id,
    validate_vault_path,
)
from lifeos.registry.coherent_tracking import register_scan as _coherent_register_scan
from lifeos.registry.proposals import (
    ProposalQueryError,
    ProposalScanError,
    ProposalSummary,
    count_proposals_by_status,
    list_proposals,
    register_proposals_scan,
)
from lifeos.scanner import VaultFile

from lifeos.registry.provenance import (
    ProvenanceIndexError,
    ProvenanceSourceSummary,
    DerivedProvenanceSummary,
    ProvenanceDocumentRow,
    ProvenanceSourceRow,
    refresh_provenance_index,
    get_provenance_for_derived,
    list_derived_for_source,
)


def _scrub_out_of_scope_content_metadata(
    registry: Registry,
    *,
    allow_path: Callable[[str], bool],
) -> None:
    """Forget stale content-derived facts that a scoped refresh may no longer inspect."""
    with registry.connect() as connection:
        rows = connection.execute(
            """
            SELECT id, vault_path
            FROM files
            WHERE stable_id IS NOT NULL OR content_hash IS NOT NULL OR mtime_ns IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            path = str(row["vault_path"])
            if path.startswith(".lifeos/registry-tombstones/"):
                remainder = path[len(".lifeos/registry-tombstones/") :]
                _row_id, separator, prior_path = remainder.partition("/")
                if separator and prior_path:
                    path = prior_path
            if allow_path(path):
                continue
            connection.execute(
                """
                UPDATE files
                SET stable_id = NULL, content_hash = NULL, mtime_ns = NULL
                WHERE id = ?
                """,
                (int(row["id"]),),
            )
        connection.commit()


def register_scan(
    registry: Registry,
    vault_root: Path,
    entries: list[VaultFile],
    *,
    identity_allow_path: Callable[[str], bool] | None = None,
) -> ScanResult:
    """Register canonical scan entries while excluding this registry's runtime subtree.

    A custom in-vault runtime directory is disposable node-local state just like the default
    ``.lifeos`` directory. ``scan_vault`` already ignores the default name, while this boundary
    removes any configured custom runtime subtree before content access. When an identity scope
    predicate is supplied, denied paths remain presence-only registry rows: their bytes are not
    opened, and any content-derived metadata left by an earlier broader refresh is scrubbed.
    """
    # Config loading and Registry construction already normalize their paths. Use a lexical
    # absolute conversion here instead of Path.resolve(): the latter performs filesystem stat
    # calls and would consume the historical change-during-hash observation seam before
    # `_hash_file` gets to inspect the canonical file itself.
    root = Path(os.path.abspath(os.fspath(vault_root)))
    runtime_dir = registry.database_path.parent
    try:
        relative_runtime = runtime_dir.relative_to(root)
    except ValueError:
        canonical_entries = entries
    else:
        if relative_runtime == Path("."):
            raise FileTrackingError(
                "Registry runtime directory overlaps the canonical vault root; scan is unsafe"
            )
        prefix = relative_runtime.parts
        canonical_entries = [
            entry
            for entry in entries
            if entry.path.parts[: len(prefix)] != prefix
        ]
    result = _coherent_register_scan(
        registry,
        root,
        canonical_entries,
        identity_allow_path=identity_allow_path,
    )
    if identity_allow_path is not None:
        _scrub_out_of_scope_content_metadata(
            registry,
            allow_path=identity_allow_path,
        )
    return result


# Keep direct ``lifeos.registry.file_tracking.register_scan`` imports aligned with the public API.
setattr(_file_tracking, "register_scan", register_scan)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DerivedProvenanceSummary",
    "FileComparison",
    "FileRegistrationState",
    "FileTrackingError",
    "ProposalQueryError",
    "ProposalScanError",
    "ProposalSummary",
    "ProvenanceDocumentRow",
    "ProvenanceIndexError",
    "ProvenanceSourceRow",
    "ProvenanceSourceSummary",
    "RegisteredStableIdentity",
    "Registry",
    "RegistryError",
    "RegistryHistoryError",
    "RegistryMigrationError",
    "RegistryOpenError",
    "ScanResult",
    "UnsupportedSchemaVersionError",
    "compare_registered_file",
    "count_proposals_by_status",
    "get_provenance_for_derived",
    "hash_file_content",
    "list_derived_for_source",
    "list_proposals",
    "list_registered_stable_identities",
    "refresh_provenance_index",
    "register_proposals_scan",
    "register_scan",
    "resolve_registered_stable_id",
    "validate_vault_path",
]
