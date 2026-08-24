"""Facade operations for rebuilding disposable registry state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lifeos.facade.errors import ToolExecutionError
from lifeos.facade.models import ToolDescriptor, ToolEffect
from lifeos.registry import (
    FileTrackingError,
    ProposalScanError,
    Registry,
    RegistryError,
    count_proposals_by_status,
    register_proposals_scan,
    register_scan,
)
from lifeos.scanner import ScannerError, scan_vault


REGISTRY_REFRESH_DESCRIPTOR = ToolDescriptor(
    name="registry.refresh",
    description=(
        "Refresh disposable file and proposal registry indexes from canonical vault state."
    ),
    effect=ToolEffect.DERIVED_WRITE,
)


@dataclass(frozen=True, slots=True)
class RegistryRefreshResult:
    new: tuple[str, ...]
    modified: tuple[str, ...]
    unchanged: tuple[str, ...]
    deleted: tuple[str, ...]
    proposals_indexed: int
    renamed: tuple[tuple[str, str], ...] = ()


def refresh_registry(*, vault_root: Path, registry: Registry) -> RegistryRefreshResult:
    """Rebuild disposable registry facts without changing canonical vault files."""
    try:
        registry.initialize()
        scan_result = register_scan(registry, vault_root, scan_vault(vault_root))
        register_proposals_scan(registry, vault_root=vault_root)
        with registry.connect_read_only() as connection:
            proposals_indexed = sum(count_proposals_by_status(connection).values())
    except (ScannerError, FileTrackingError, ProposalScanError, RegistryError) as error:
        raise ToolExecutionError("Could not refresh the disposable registry") from error

    return RegistryRefreshResult(
        new=tuple(scan_result.new),
        modified=tuple(scan_result.modified),
        unchanged=tuple(scan_result.unchanged),
        deleted=tuple(scan_result.deleted),
        proposals_indexed=proposals_indexed,
        renamed=tuple(scan_result.renamed),
    )
