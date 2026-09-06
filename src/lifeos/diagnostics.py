"""Typed, sanitized diagnostics shared by derived-domain loaders."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal

from lifeos.markdown.parser import ParseFinding

DiagnosticSeverity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class DomainDiagnostic:
    code: str
    severity: DiagnosticSeverity
    source_path: str
    line: int
    message: str


class DiagnosticError(ValueError):
    """An operation failed with one sanitized diagnostic."""

    def __init__(self, message: str, *, diagnostic: DomainDiagnostic | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _relative_path(path: Path, vault_root: Path) -> str:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return path.name


def diagnostics_from_findings(
    findings: Iterable[ParseFinding],
    *,
    vault_root: Path,
) -> tuple[DomainDiagnostic, ...]:
    diagnostics = {
        DomainDiagnostic(
            code=finding.code,
            severity=finding.severity,
            source_path=_relative_path(finding.path, vault_root),
            line=finding.line,
            message=_sanitize_message(finding.message),
        )
        for finding in findings
    }
    return tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.source_path,
                item.line,
                item.code,
                item.severity,
                item.message,
            ),
        )
    )


def _sanitize_message(message: str) -> str:
    collapsed = " ".join(message.split())
    return collapsed[:300]


def diagnostic_error_message(diagnostic: DomainDiagnostic) -> str:
    return f"{diagnostic.source_path}:{diagnostic.line}: [{diagnostic.code}] {diagnostic.message}"


def serialize_diagnostic_error(error: DiagnosticError) -> str:
    diagnostic = error.diagnostic
    payload: dict[str, object] = {
        "error": "domain-diagnostic" if diagnostic is not None else "domain-error",
        "message": str(error),
    }
    if diagnostic is not None:
        payload["diagnostic"] = asdict(diagnostic)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
