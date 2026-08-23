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
from lifeos.config import LifeOSConfig
from lifeos.registry import Registry
from lifeos.status import StatusResult, collect_status, serialize_status_json

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
    vault_status: StatusResult
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
    return DoctorFinding(
        "git", "healthy", "git-ready", f"Git is available at {executable}."
    )


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


def collect_doctor(config: LifeOSConfig, *, config_path: Path) -> DoctorResult:
    """Collect readiness without repairing or mutating application, vault, or client state."""
    registry = Registry(config.runtime_dir / "registry.db")
    vault_status = collect_status(config, registry)
    mcp_findings, mcp_command = _mcp_findings(config_path)
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
        *mcp_findings,
    )
    blocked = (
        any(finding.state == "blocked" for finding in findings)
        or vault_status.exit_code != 0
    )
    return DoctorResult(
        lifeos_version=__version__,
        config_path=str(config_path.resolve()),
        vault_root=str(config.vault_root),
        ready=not blocked,
        exit_code=1 if blocked else 0,
        findings=findings,
        vault_status=vault_status,
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
        "Readiness checks",
    ]
    for finding in result.findings:
        lines.append(
            f"  {finding.subsystem}: {finding.state} "
            f"[{finding.code}] - {finding.detail}"
        )
        if finding.next_action:
            lines.append(f"    next: {finding.next_action}")

    lines.extend(["", f"Vault health: {result.vault_status.overall_state}"])
    for check in result.vault_status.checks:
        lines.append(
            f"  {check.subsystem}: {check.state} [{check.code}] - {check.detail}"
        )
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
        "vault": json.loads(serialize_status_json(result.vault_status)),
        "mcp_command": list(result.mcp_command) if result.mcp_command else None,
    }
    return json.dumps(data, indent=2)
