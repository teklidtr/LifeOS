"""Read-only installation and vault readiness diagnostics for LifeOS."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from lifeos import __version__
from lifeos.bootstrap import is_recognized_vault
from lifeos.coherence import (
    CoherenceError,
    IdentityDiagnostic,
    VaultTopology,
    describe_topology,
)
from lifeos.coherence_scoped import collect_scoped_identity_snapshot
from lifeos.config import LifeOSConfig
from lifeos.recovery_readiness import (
    RecoveryReport,
    collect_recovery_readiness,
    format_recovery_text,
    recovery_report_to_dict,
)
from lifeos.registry import Registry
from lifeos.status import StatusResult, collect_status, status_result_to_dict

FindingState = Literal["healthy", "warning", "blocked"]


@dataclass(frozen=True, slots=True)
class DoctorFinding:
    """One deterministic readiness finding."""

    subsystem: str
    state: FindingState
    code: str
    detail: str
    next_action: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorResult:
    """Read-only application and vault readiness result."""

    lifeos_version: str
    config_path: str
    vault_root: str
    ready: bool
    exit_code: int
    findings: tuple[DoctorFinding, ...]
    recovery: RecoveryReport
    vault_status: StatusResult
    topology: VaultTopology
    identity_note_count: int
    relocation_safe_note_count: int
    identity_diagnostics: tuple[IdentityDiagnostic, ...]
    mcp_command: tuple[str, ...] | None = None


def _python_finding() -> DoctorFinding:
    current = sys.version_info[:3]
    version = f"{current[0]}.{current[1]}.{current[2]}"
    if current < (3, 11, 0):
        return DoctorFinding(
            "python",
            "blocked",
            "python-unsupported",
            f"Python {version} is unsupported; LifeOS requires Python 3.11+.",
            "Install Python 3.11 or newer and reinstall LifeOS.",
        )
    return DoctorFinding(
        "python",
        "healthy",
        "python-supported",
        f"Python {version} is supported.",
    )


def _git_finding() -> DoctorFinding:
    executable = shutil.which("git")
    if executable is None:
        return DoctorFinding(
            "git",
            "blocked",
            "git-missing",
            "Git is not available on PATH.",
            "Install Git and make it available on PATH.",
        )
    return DoctorFinding("git", "healthy", "git-ready", f"Git is available at {executable}.")


def _bootstrap_finding(config: LifeOSConfig) -> DoctorFinding:
    if is_recognized_vault(config.vault_root):
        return DoctorFinding(
            "vault-bootstrap",
            "healthy",
            "vault-bootstrap-valid",
            "Vault matches the current first-party LifeOS bootstrap shape.",
        )
    return DoctorFinding(
        "vault-bootstrap",
        "blocked",
        "vault-bootstrap-invalid",
        "Configured vault does not match the current first-party LifeOS bootstrap shape.",
        "Inspect the vault bootstrap files and roots; do not run repair commands blindly.",
    )


def _mcp_findings(config_path: Path) -> tuple[tuple[DoctorFinding, ...], tuple[str, ...] | None]:
    sdk_available = importlib.util.find_spec("mcp") is not None
    executable = shutil.which("lifeos-mcp")
    findings: list[DoctorFinding] = []

    if sdk_available:
        findings.append(
            DoctorFinding(
                "mcp-sdk",
                "healthy",
                "mcp-sdk-ready",
                "Optional MCP SDK is installed.",
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "mcp-sdk",
                "warning",
                "mcp-sdk-missing",
                "Optional MCP SDK is not installed; core local vault use remains available.",
                "Install the LifeOS MCP extra when an external MCP client is needed.",
            )
        )

    if executable is None:
        findings.append(
            DoctorFinding(
                "mcp-server",
                "warning",
                "mcp-executable-missing",
                "lifeos-mcp is not available on PATH; core local vault use remains available.",
                "Install the LifeOS MCP extra and expose the lifeos-mcp console script when needed.",
            )
        )
        return tuple(findings), None

    command = (
        executable,
        "--config",
        str(config_path.resolve()),
        "--actor-id",
        "<actor-id>",
    )
    findings.append(
        DoctorFinding(
            "mcp-server",
            "healthy",
            "mcp-executable-ready",
            f"lifeos-mcp is available at {executable}.",
        )
    )
    return tuple(findings), command


def _coherence_findings(
    topology: VaultTopology,
    diagnostics: tuple[IdentityDiagnostic, ...],
) -> tuple[DoctorFinding, ...]:
    findings: list[DoctorFinding] = [
        DoctorFinding(
            "vault-coherence",
            "healthy",
            "single-active-writer",
            (
                "Cross-device mutation authority is defined as one active LifeOS writer; "
                "synchronized replicas remain human-editable clients rather than independent writers."
            ),
        )
    ]
    if topology.runtime_location == "inside-canonical-vault":
        runtime_exclusion = topology.required_sync_exclusions[0]
        findings.append(
            DoctorFinding(
                "vault-coherence",
                "warning",
                "runtime-state-sync-exclusion-required",
                (
                    "Disposable runtime state is inside the canonical vault tree and must remain "
                    "excluded from synchronization/authoritative backup semantics."
                ),
                (
                    f"Keep {runtime_exclusion} excluded from synchronization; prefer node-local "
                    "runtime storage when practical."
                ),
            )
        )
    else:
        findings.append(
            DoctorFinding(
                "vault-coherence",
                "healthy",
                "runtime-state-node-local",
                "Disposable runtime state is located outside the canonical vault tree.",
            )
        )

    for diagnostic in diagnostics:
        if diagnostic.code == "stable-id-ambiguous":
            findings.append(
                DoctorFinding(
                    "vault-identity",
                    "blocked",
                    diagnostic.code,
                    diagnostic.detail,
                    "Assign unique frontmatter ids before proposal mutation or relocation-aware workflows.",
                )
            )
        elif diagnostic.code == "stable-id-missing":
            findings.append(
                DoctorFinding(
                    "vault-identity",
                    "warning",
                    diagnostic.code,
                    diagnostic.detail,
                    "Add a durable frontmatter id when this wiki note next enters a reviewed migration workflow.",
                )
            )
    return tuple(findings)


def collect_doctor(config: LifeOSConfig, *, config_path: Path) -> DoctorResult:
    """Collect readiness without repairing or mutating application, vault, or client state."""
    registry = Registry(config.runtime_dir / "registry.db")
    vault_status = collect_status(config, registry)
    recovery = collect_recovery_readiness(config)
    mcp_findings, mcp_command = _mcp_findings(config_path)
    topology = describe_topology(config)
    coherence_findings: tuple[DoctorFinding, ...]

    try:
        identity_snapshot = collect_scoped_identity_snapshot(
            config.vault_root,
            allow_path=lambda _path: True,
            runtime_dir=config.runtime_dir,
        )
    except CoherenceError as error:
        identity_note_count = 0
        relocation_safe_note_count = 0
        identity_diagnostics: tuple[IdentityDiagnostic, ...] = (
            IdentityDiagnostic(
                severity="blocked",
                code="identity-scan-failed",
                detail=str(error),
            ),
        )
        coherence_findings = (
            DoctorFinding(
                "vault-identity",
                "blocked",
                "identity-scan-failed",
                str(error),
                "Inspect vault readability and retry after the canonical filesystem view is coherent.",
            ),
        )
    else:
        identity_note_count = len(identity_snapshot.notes)
        relocation_safe_note_count = sum(
            1 for note in identity_snapshot.notes if note.relocation_safe
        )
        identity_diagnostics = identity_snapshot.diagnostics
        coherence_findings = _coherence_findings(topology, identity_diagnostics)

    findings = (
        DoctorFinding(
            "application",
            "healthy",
            "lifeos-version",
            f"LifeOS {__version__} is installed.",
        ),
        _python_finding(),
        _git_finding(),
        _bootstrap_finding(config),
        *coherence_findings,
        *mcp_findings,
    )
    blocked = any(finding.state == "blocked" for finding in findings) or vault_status.exit_code != 0
    return DoctorResult(
        lifeos_version=__version__,
        config_path=str(config_path.resolve()),
        vault_root=str(config.vault_root),
        ready=not blocked,
        exit_code=1 if blocked else 0,
        findings=findings,
        recovery=recovery,
        vault_status=vault_status,
        topology=topology,
        identity_note_count=identity_note_count,
        relocation_safe_note_count=relocation_safe_note_count,
        identity_diagnostics=identity_diagnostics,
        mcp_command=mcp_command,
    )


def format_doctor_text(result: DoctorResult) -> str:
    """Format a concise human-readable readiness report."""
    lines = [
        "LifeOS doctor",
        f"Ready: {'yes' if result.ready else 'no'}",
        f"LifeOS: {result.lifeos_version}",
        f"Config: {result.config_path}",
        f"Vault: {result.vault_root}",
        "",
        "Cross-device coherence",
        f"  writer model: {result.topology.writer_model}",
        f"  runtime state: {result.topology.runtime_location}",
        (
            "  stable identities: "
            f"{result.relocation_safe_note_count}/{result.identity_note_count} Markdown notes"
        ),
        "  required sync exclusions:",
    ]
    lines.extend(f"    - {exclusion}" for exclusion in result.topology.required_sync_exclusions)
    lines.extend(["", "Readiness checks"])
    for finding in result.findings:
        lines.append(f"  {finding.subsystem}: {finding.state} [{finding.code}] - {finding.detail}")
        if finding.next_action:
            lines.append(f"    next: {finding.next_action}")

    lines.extend(["", *format_recovery_text(result.recovery)])
    lines.extend(["", f"Vault health: {result.vault_status.overall_state}"])
    for check in result.vault_status.checks:
        lines.append(f"  {check.subsystem}: {check.state} [{check.code}] - {check.detail}")
        if check.next_action:
            lines.append(f"    next: {check.next_action}")

    if result.mcp_command:
        lines.extend(["", "MCP server command template", f"  {' '.join(result.mcp_command)}"])
        lines.append(
            "  Replace <actor-id> and configure this command explicitly in your MCP client."
        )
    return "\n".join(lines)


def serialize_doctor_json(result: DoctorResult) -> str:
    """Serialize the stable doctor result shape."""
    data = {
        "ready": result.ready,
        "exit_code": result.exit_code,
        "application": {
            "lifeos_version": result.lifeos_version,
            "config_path": result.config_path,
            "vault_root": result.vault_root,
        },
        "findings": [asdict(finding) for finding in result.findings],
        "recovery": recovery_report_to_dict(result.recovery),
        "vault": status_result_to_dict(result.vault_status),
        "coherence": {
            "topology": result.topology.to_dict(),
            "identity_note_count": result.identity_note_count,
            "relocation_safe_note_count": result.relocation_safe_note_count,
            "identity_diagnostics": [
                diagnostic.to_dict() for diagnostic in result.identity_diagnostics
            ],
        },
        "mcp_command": list(result.mcp_command) if result.mcp_command else None,
    }
    return json.dumps(data, indent=2)
