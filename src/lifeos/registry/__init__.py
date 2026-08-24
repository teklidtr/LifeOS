"""Public SQLite registry interface for deterministic LifeOS state."""

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
    removes any configured custom runtime subtree before file hashing or stable-ID parsing. An
    optional identity predicate scopes only stable-ID interpretation; ordinary file/hash tracking
    still covers every canonical entry supplied to this boundary.
    """
    root = Path(vault_root).resolve(strict=False)
    runtime_dir = registry.database_path.parent.resolve(strict=False)
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
    return _coherent_register_scan(
        registry,
        root,
        canonical_entries,
        identity_allow_path=identity_allow_path,
    )


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
