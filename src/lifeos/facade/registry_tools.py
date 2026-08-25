"""Facade operations for rebuilding disposable registry state."""

from __future__ import annotations

from collections.abc import Callable
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


def refresh_registry(
    *,
    vault_root: Path,
    registry: Registry,
    identity_allow_path: Callable[[str], bool] | None = None,
) -> RegistryRefreshResult:
    """Rebuild disposable registry facts without changing canonical vault files.

    An unscoped local refresh rebuilds both file facts and the Git-tracked proposal index.
    Supplying ``identity_allow_path`` marks an externally scoped refresh: path metadata may be
    reconciled without opening denied file content, and proposal artifacts are deliberately not
    indexed because that namespace is outside the external retrieval scope. Existing proposal
    index rows remain disposable local state and are not exposed as proof that excluded proposal
    content was inspected by the external call.
    """
    try:
        registry.initialize()
        scan_result = register_scan(
            registry,
            vault_root,
            scan_vault(vault_root),
            identity_allow_path=identity_allow_path,
        )
        if identity_allow_path is None:
            register_proposals_scan(registry, vault_root=vault_root)
            with registry.connect_read_only() as connection:
                proposals_indexed = sum(count_proposals_by_status(connection).values())
        else:
            proposals_indexed = 0
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
