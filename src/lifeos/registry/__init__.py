"""Public SQLite registry interface for deterministic LifeOS state."""

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
    validate_vault_path,
    FileRegistrationState,
    FileTrackingError,
    ScanResult,
    compare_registered_file,
    hash_file_content,
    register_scan,
)
from lifeos.registry.proposals import (
    ProposalQueryError,
    ProposalScanError,
    ProposalSummary,
    count_proposals_by_status,
    list_proposals,
    register_proposals_scan,
)

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
    "refresh_provenance_index",
    "register_proposals_scan",
    "register_scan",
    "validate_vault_path",
]
