"""Typed, read-only LifeOS status collection and formatting."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Literal

from lifeos.config import LifeOSConfig
from lifeos.exports import ExportError, export_status
from lifeos.graph import GraphError, graph_view_status
from lifeos.lint import lint_vault
from lifeos.ownership import GeneratedOwnership, ManifestError, PathSafetyError
from lifeos.proposals.recovery import (
    RecoveryCorruptStateError,
    RecoveryUnavailableError,
    discover_recovery_state,
)
from lifeos.proposals.schema import ProposalStatus
from lifeos.publication import PublicationError
from lifeos.registry import (
    Registry,
    RegistryHistoryError,
    RegistryOpenError,
    UnsupportedSchemaVersionError,
)
from lifeos.registry._registry import _migration_plan
from lifeos.registry.proposals import ProposalQueryError, count_proposals_by_status
from lifeos.scanner import ScannerError, scan_vault

RegistryState = Literal["missing", "uninitialized", "initialized", "unreadable", "unsupported"]
DiagnosticState = Literal["healthy", "stale", "unavailable", "corrupt", "blocked", "unsupported"]
OverallState = Literal["healthy", "degraded", "blocked"]

_GRAPH_VIEWS = ("knowledge", "provenance", "personal-patterns", "system")
_EXPORT_KINDS = ("public-wiki", "study-bundle", "trusted-agent", "personal-review")


@dataclass(frozen=True, slots=True)
class RegistryStatus:
    state: RegistryState
    schema_version: int | None
    database_path: str


@dataclass(frozen=True, slots=True)
class FileStatusCounts:
    active: int
    deleted: int
    comparison_available: bool = False


@dataclass(frozen=True, slots=True)
class LintStatusCounts:
    errors: int
    warnings: int
    suggestions: int


@dataclass(frozen=True, slots=True)
class FeatureStatus:
    graphify: bool
    exports: bool


@dataclass(frozen=True, slots=True)
class SubsystemStatus:
    subsystem: str
    state: DiagnosticState
    code: str
    detail: str
    next_action: str | None = None


@dataclass(frozen=True, slots=True)
class StatusResult:
    registry: RegistryStatus
    files: FileStatusCounts | None
    lint: LintStatusCounts | None
    features: FeatureStatus
    proposals: tuple[tuple[ProposalStatus, int], ...] | None = None
    checks: tuple[SubsystemStatus, ...] = ()
    overall_state: OverallState = "healthy"
    exit_code: int = 0


def _safe_database_path(config: LifeOSConfig, registry: Registry) -> str:
    if registry.database_path.is_relative_to(config.vault_root):
        return str(registry.database_path.relative_to(config.vault_root))
    return "<external-runtime>/registry.db"


def _registry_status(
    registry: Registry, database_path: str
) -> tuple[RegistryStatus, SubsystemStatus]:
    if not registry.database_path.exists():
        return (
            RegistryStatus("missing", None, database_path),
            SubsystemStatus(
                "registry",
                "unavailable",
                "registry-missing",
                "The disposable registry has not been created.",
                "Run the registry initialization or rebuild command.",
            ),
        )
    try:
        schema_version = registry.schema_version
        latest = _migration_plan()[-1].version
        if schema_version == latest:
            return (
                RegistryStatus("initialized", schema_version, database_path),
                SubsystemStatus(
                    "registry", "healthy", "registry-ready", "Registry schema is current."
                ),
            )
        return (
            RegistryStatus("uninitialized", schema_version, database_path),
            SubsystemStatus(
                "registry",
                "stale",
                "registry-incomplete",
                "Registry schema is not fully initialized.",
                "Rebuild the disposable registry.",
            ),
        )
    except UnsupportedSchemaVersionError:
        return (
            RegistryStatus("unsupported", None, database_path),
            SubsystemStatus(
                "registry",
                "unsupported",
                "registry-schema-unsupported",
                "Registry schema is newer than this LifeOS version supports.",
                "Upgrade LifeOS before reading this registry.",
            ),
        )
    except RegistryHistoryError as exc:
        if isinstance(exc.__cause__, sqlite3.Error):
            return (
                RegistryStatus("unreadable", None, database_path),
                SubsystemStatus(
                    "registry",
                    "corrupt",
                    "registry-corrupt",
                    "Registry history could not be read.",
                    "Rebuild the disposable registry.",
                ),
            )
        return (
            RegistryStatus("uninitialized", None, database_path),
            SubsystemStatus(
                "registry",
                "stale",
                "registry-history-missing",
                "Registry history is incomplete.",
                "Rebuild the disposable registry.",
            ),
        )
    except RegistryOpenError:
        return (
            RegistryStatus("unreadable", None, database_path),
            SubsystemStatus(
                "registry",
                "unavailable",
                "registry-open-failed",
                "Registry storage is currently unavailable.",
                "Check runtime-directory permissions and retry.",
            ),
        )
    except sqlite3.Error:
        return (
            RegistryStatus("unreadable", None, database_path),
            SubsystemStatus(
                "registry",
                "corrupt",
                "registry-sqlite-error",
                "Registry data could not be decoded.",
                "Rebuild the disposable registry.",
            ),
        )


def _registry_content_status(
    registry: Registry, registry_state: RegistryState
) -> tuple[
    FileStatusCounts | None,
    tuple[tuple[ProposalStatus, int], ...] | None,
    SubsystemStatus,
    SubsystemStatus,
]:
    if registry_state != "initialized":
        unavailable = SubsystemStatus(
            "files",
            "unavailable",
            "files-registry-unavailable",
            "Registered file counts require an initialized registry.",
        )
        proposals = SubsystemStatus(
            "proposals",
            "unavailable",
            "proposals-registry-unavailable",
            "Proposal counts require an initialized registry.",
        )
        return None, None, unavailable, proposals

    files_status: FileStatusCounts | None = None
    proposals_counts: tuple[tuple[ProposalStatus, int], ...] | None = None
    files_check = SubsystemStatus(
        "files", "unavailable", "files-query-failed", "Registered file counts are unavailable."
    )
    proposals_check = SubsystemStatus(
        "proposals",
        "unavailable",
        "proposals-query-failed",
        "Proposal counts are unavailable.",
    )
    try:
        with registry._connection(create=False, read_only=True) as conn:
            try:
                row = conn.execute(
                    "SELECT SUM(is_deleted = 0) AS active_count, "
                    "SUM(is_deleted = 1) AS deleted_count FROM files"
                ).fetchone()
                active = (row["active_count"] or 0) if row else 0
                deleted = (row["deleted_count"] or 0) if row else 0
                files_status = FileStatusCounts(active=active, deleted=deleted)
                files_check = SubsystemStatus(
                    "files", "healthy", "files-counted", "Registered file counts are readable."
                )
            except sqlite3.Error:
                files_check = SubsystemStatus(
                    "files",
                    "corrupt",
                    "files-query-corrupt",
                    "Registered file rows could not be queried.",
                    "Rebuild the disposable registry.",
                )

            try:
                raw_counts = count_proposals_by_status(conn)
                proposals_counts = tuple(
                    (status, raw_counts.get(status, 0)) for status in ProposalStatus
                )
                proposals_check = SubsystemStatus(
                    "proposals",
                    "healthy",
                    "proposals-counted",
                    "Proposal index counts are readable.",
                )
            except ProposalQueryError:
                proposals_check = SubsystemStatus(
                    "proposals",
                    "corrupt",
                    "proposals-query-corrupt",
                    "Proposal index rows could not be queried.",
                    "Rebuild the disposable registry.",
                )
    except (RegistryOpenError, RegistryHistoryError, sqlite3.Error):
        pass
    return files_status, proposals_counts, files_check, proposals_check


def _lint_status(config: LifeOSConfig) -> tuple[LintStatusCounts | None, SubsystemStatus]:
    manifest_path = config.runtime_dir / "ownership.json"
    try:
        scanned_files = scan_vault(config.vault_root)
        lint_result = lint_vault(
            vault_root=config.vault_root,
            files=scanned_files,
            manifest_path=manifest_path,
        )
    except (ScannerError, OSError, UnicodeError):
        return None, SubsystemStatus(
            "lint",
            "unavailable",
            "lint-unavailable",
            "Canonical vault linting could not complete.",
            "Check vault readability and retry.",
        )
    counts = LintStatusCounts(
        errors=lint_result.error_count,
        warnings=lint_result.warning_count,
        suggestions=lint_result.suggestion_count,
    )
    if counts.errors:
        return counts, SubsystemStatus(
            "lint",
            "corrupt",
            "lint-errors",
            f"Vault lint reported {counts.errors} error(s).",
            "Run the lint command and resolve canonical-note errors.",
        )
    if counts.warnings:
        return counts, SubsystemStatus(
            "lint",
            "stale",
            "lint-warnings",
            f"Vault lint reported {counts.warnings} warning(s).",
            "Review lint warnings when convenient.",
        )
    return counts, SubsystemStatus(
        "lint", "healthy", "lint-clean", "Vault lint completed without errors."
    )


def _ownership_status(config: LifeOSConfig) -> SubsystemStatus:
    manifest_path = config.vault_root / "system" / "generated-ownership.json"
    if not manifest_path.exists():
        return SubsystemStatus(
            "ownership",
            "healthy",
            "ownership-absent",
            "No generated ownership manifest is present.",
        )
    try:
        GeneratedOwnership.load(manifest_path, config.vault_root)
    except PathSafetyError:
        return SubsystemStatus(
            "ownership",
            "corrupt",
            "ownership-unsafe-path",
            "Generated ownership uses an unsafe path.",
            "Inspect and repair the canonical ownership manifest.",
        )
    except ManifestError:
        return SubsystemStatus(
            "ownership",
            "corrupt",
            "ownership-invalid",
            "Generated ownership manifest is invalid.",
            "Inspect and repair the canonical ownership manifest.",
        )
    except OSError:
        return SubsystemStatus(
            "ownership",
            "unavailable",
            "ownership-unavailable",
            "Generated ownership manifest is not readable.",
            "Check vault permissions and retry.",
        )
    return SubsystemStatus(
        "ownership", "healthy", "ownership-valid", "Generated ownership is valid."
    )


def _recovery_status(config: LifeOSConfig) -> SubsystemStatus:
    try:
        discovery = discover_recovery_state(recovery_root=config.runtime_dir / "recovery")
    except RecoveryCorruptStateError:
        return SubsystemStatus(
            "recovery",
            "corrupt",
            "recovery-root-corrupt",
            "Recovery state is structurally corrupt.",
            "Inspect recovery state before applying another proposal.",
        )
    except RecoveryUnavailableError:
        return SubsystemStatus(
            "recovery",
            "unavailable",
            "recovery-unavailable",
            "Recovery state could not be read.",
            "Check runtime-directory permissions before applying proposals.",
        )
    if discovery.findings:
        return SubsystemStatus(
            "recovery",
            "corrupt",
            "recovery-findings",
            f"Recovery discovery reported {len(discovery.findings)} finding(s).",
            "Inspect recovery state before applying another proposal.",
        )
    incomplete = tuple(
        journal for journal in discovery.journals if journal.phase.value != "complete"
    )
    if incomplete:
        return SubsystemStatus(
            "recovery",
            "blocked",
            "recovery-pending",
            f"{len(incomplete)} interrupted application transaction(s) require recovery.",
            "Run proposal recovery before applying another proposal.",
        )
    return SubsystemStatus(
        "recovery", "healthy", "recovery-clear", "No interrupted application is pending."
    )


def _graph_status(config: LifeOSConfig) -> SubsystemStatus:
    if not config.features.graphify:
        return SubsystemStatus(
            "graph", "unsupported", "graph-disabled", "Graph views are disabled by configuration."
        )
    try:
        states = tuple(
            graph_view_status(
                vault_root=config.vault_root,
                runtime_dir=config.runtime_dir,
                view_name=view,
            )
            for view in _GRAPH_VIEWS
        )
    except (GraphError, PublicationError, OSError):
        return SubsystemStatus(
            "graph",
            "unavailable",
            "graph-status-unavailable",
            "Graph publication state could not be inspected.",
            "Check runtime-directory permissions and graph state.",
        )
    if any(state.status == "failed" for state in states):
        return SubsystemStatus(
            "graph",
            "corrupt",
            "graph-publication-corrupt",
            "At least one graph view has corrupt publication state.",
            "Rebuild the affected graph view.",
        )
    if any(state.status == "unavailable" for state in states):
        return SubsystemStatus(
            "graph",
            "unavailable",
            "graph-integrity-unavailable",
            "At least one graph generation could not be verified.",
            "Check runtime storage permissions and retry.",
        )
    if any(state.status == "unsupported" for state in states):
        return SubsystemStatus(
            "graph",
            "stale",
            "graph-rebuild-required",
            "At least one graph generation predates integrity inventories.",
            "Rebuild the affected graph view.",
        )
    if any(state.status == "dirty" for state in states):
        return SubsystemStatus(
            "graph",
            "stale",
            "graph-stale",
            "At least one graph view is stale.",
            "Rebuild graph views when current derived output is needed.",
        )
    if all(state.status == "missing" for state in states):
        return SubsystemStatus(
            "graph",
            "unavailable",
            "graph-missing",
            "No graph view has been built.",
            "Build a graph view when needed.",
        )
    return SubsystemStatus("graph", "healthy", "graph-ready", "Graph views are readable.")


def _export_status(config: LifeOSConfig) -> SubsystemStatus:
    if not config.features.exports:
        return SubsystemStatus(
            "exports", "unsupported", "exports-disabled", "Exports are disabled by configuration."
        )
    try:
        states = tuple(
            export_status(
                vault_root=config.vault_root,
                runtime_dir=config.runtime_dir,
                kind=kind,
            )
            for kind in _EXPORT_KINDS
        )
    except (ExportError, PublicationError, OSError):
        return SubsystemStatus(
            "exports",
            "unavailable",
            "exports-status-unavailable",
            "Export publication state could not be inspected.",
            "Check runtime-directory permissions and export state.",
        )
    if any(state.status == "failed" for state in states):
        return SubsystemStatus(
            "exports",
            "corrupt",
            "exports-publication-corrupt",
            "At least one export has corrupt publication state.",
            "Rebuild the affected export.",
        )
    if any(state.status == "unavailable" for state in states):
        return SubsystemStatus(
            "exports",
            "unavailable",
            "exports-integrity-unavailable",
            "At least one export generation could not be verified.",
            "Check runtime storage permissions and retry.",
        )
    if any(state.status == "unsupported" for state in states):
        return SubsystemStatus(
            "exports",
            "stale",
            "exports-rebuild-required",
            "At least one export generation predates integrity inventories.",
            "Rebuild the affected export.",
        )
    if any(state.status == "stale" for state in states):
        return SubsystemStatus(
            "exports",
            "stale",
            "exports-stale",
            "At least one export no longer represents current canonical input.",
            "Rebuild the affected export when current derived output is needed.",
        )
    if all(state.status == "missing" for state in states):
        return SubsystemStatus(
            "exports",
            "unavailable",
            "exports-missing",
            "No export bundle has been built.",
            "Build an export bundle when needed.",
        )
    return SubsystemStatus(
        "exports", "healthy", "exports-ready", "Export publication state is readable."
    )


def _overall(checks: tuple[SubsystemStatus, ...]) -> tuple[OverallState, int]:
    if any(check.state == "blocked" for check in checks):
        return "blocked", 2
    if any(check.state in {"stale", "unavailable", "corrupt"} for check in checks):
        return "degraded", 0
    return "healthy", 0


def collect_status(config: LifeOSConfig, registry: Registry) -> StatusResult:
    """Collect partial status without mutating the vault or masking programmer defects."""
    database_path = _safe_database_path(config, registry)
    registry_status, registry_check = _registry_status(registry, database_path)
    files, proposals, files_check, proposals_check = _registry_content_status(
        registry, registry_status.state
    )
    lint, lint_check = _lint_status(config)
    checks = (
        SubsystemStatus("configuration", "healthy", "config-valid", "Configuration is valid."),
        registry_check,
        files_check,
        lint_check,
        proposals_check,
        _ownership_status(config),
        _recovery_status(config),
        _graph_status(config),
        _export_status(config),
    )
    overall_state, exit_code = _overall(checks)
    return StatusResult(
        registry=registry_status,
        files=files,
        lint=lint,
        features=FeatureStatus(graphify=config.features.graphify, exports=config.features.exports),
        proposals=proposals,
        checks=checks,
        overall_state=overall_state,
        exit_code=exit_code,
    )


def format_status_text(status: StatusResult) -> str:
    lines = ["LifeOS status", f"Overall: {status.overall_state}", ""]
    lines.append("Registry")
    lines.append(f"  state: {status.registry.state}")
    lines.append(
        "  schema version: "
        f"{status.registry.schema_version if status.registry.schema_version is not None else 'unknown'}"
    )
    lines.append(f"  database: {status.registry.database_path}\n")

    if status.files:
        lines.extend(
            [
                "Registered file state",
                f"  active: {status.files.active}",
                f"  deleted: {status.files.deleted}",
                "",
                "Current vault comparison",
                "  unavailable in read-only status\n",
            ]
        )
    else:
        lines.extend(["Registered file state", "  unavailable\n"])

    if status.lint:
        lines.extend(
            [
                "Lint",
                f"  errors: {status.lint.errors}",
                f"  warnings: {status.lint.warnings}",
                f"  suggestions: {status.lint.suggestions}\n",
            ]
        )
    else:
        lines.extend(["Lint", "  unavailable\n"])

    if status.proposals is not None:
        lines.append("Proposals")
        for index, (proposal_status, count) in enumerate(status.proposals):
            suffix = "\n" if index == len(status.proposals) - 1 else ""
            lines.append(f"  {proposal_status.value}: {count}{suffix}")
    else:
        lines.extend(["Proposals", "  unavailable\n"])

    lines.extend(
        [
            "Features",
            f"  Graphify: {'enabled' if status.features.graphify else 'disabled'}",
            f"  Exports: {'enabled' if status.features.exports else 'disabled'}",
            "",
            "Diagnostics",
        ]
    )
    for check in status.checks:
        lines.append(f"  {check.subsystem}: {check.state} [{check.code}] - {check.detail}")
        if check.next_action:
            lines.append(f"    next: {check.next_action}")
    return "\n".join(lines)


def serialize_status_json(status: StatusResult) -> str:
    files_dict = asdict(status.files) if status.files else None
    lint_dict = asdict(status.lint) if status.lint else None
    proposals_dict = (
        {proposal_status.value: count for proposal_status, count in status.proposals}
        if status.proposals is not None
        else None
    )
    data = {
        "overall_state": status.overall_state,
        "exit_code": status.exit_code,
        "registry": asdict(status.registry),
        "files": files_dict,
        "lint": lint_dict,
        "proposals": proposals_dict,
        "features": asdict(status.features),
        "checks": [asdict(check) for check in status.checks],
    }
    return json.dumps(data, indent=2)


def serialize_error_json(code: str, message: str, *, subsystem: str = "configuration") -> str:
    return json.dumps(
        {
            "error": {
                "code": code,
                "subsystem": subsystem,
                "state": "blocked",
                "message": message,
            }
        },
        indent=2,
    )
