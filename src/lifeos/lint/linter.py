from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from lifeos.markdown.parser import parse_markdown_note
from lifeos.ownership import GeneratedOwnership, ManifestError
from lifeos.ownership.manifest import stream_sha256
from lifeos.scanner import VaultFile

SEVERITY_ORDER = {
    "error": 0,
    "warning": 1,
    "suggestion": 2,
}


@dataclass(frozen=True, slots=True)
class LintFinding:
    path: Path
    code: str
    severity: Literal["error", "warning", "suggestion"]
    message: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class LintResult:
    findings: tuple[LintFinding, ...]
    error_count: int
    warning_count: int
    suggestion_count: int


def _sort_key(finding: LintFinding) -> tuple[Any, ...]:
    line_key = float("inf") if finding.line is None else finding.line
    severity_rank = SEVERITY_ORDER.get(finding.severity, 99)
    return (str(finding.path), line_key, severity_rank, finding.code, finding.message)


def lint_vault(
    vault_root: Path,
    files: Iterable[VaultFile],
    manifest_path: Path | None = None,
) -> LintResult:
    findings: list[LintFinding] = []

    # durable-id to distinct set of paths tracking
    id_to_paths: dict[str, set[str]] = defaultdict(set)

    for vf in files:
        if vf.file_type != ".md":
            continue

        abs_path = vault_root / vf.path

        try:
            parsed = parse_markdown_note(abs_path)
        except OSError as e:
            findings.append(
                LintFinding(
                    path=vf.path,
                    code="markdown-read-error",
                    severity="error",
                    message=f"Could not read markdown file: {e}",
                )
            )
            continue

        # Inherit parser findings
        for f in parsed.findings:
            if f.code == "file-read-error":
                code = "markdown-read-error"
            else:
                code = f.code
            findings.append(
                LintFinding(
                    path=vf.path, code=code, severity=f.severity, message=f.message, line=f.line
                )
            )

        # Extract fields
        status = parsed.frontmatter.get("status")
        if isinstance(status, str) and status not in ("seed", "active", "needs-review", "archived"):
            findings.append(
                LintFinding(
                    path=vf.path,
                    code="status-invalid",
                    severity="error",
                    message=f"Unsupported status value: {status}",
                )
            )

        confidence = parsed.frontmatter.get("confidence")
        if isinstance(confidence, str) and confidence not in ("low", "medium", "high"):
            findings.append(
                LintFinding(
                    path=vf.path,
                    code="confidence-invalid",
                    severity="error",
                    message=f"Unsupported confidence value: {confidence}",
                )
            )

        # Duplicate IDs tracking
        doc_id = parsed.frontmatter.get("id")
        if isinstance(doc_id, str) and doc_id.strip():
            id_to_paths[doc_id.strip()].add(str(vf.path))

    # Identify duplicate IDs
    for doc_id, paths in id_to_paths.items():
        if len(paths) > 1:
            sorted_paths = sorted(list(paths))
            for path_str in sorted_paths:
                other_paths = [p for p in sorted_paths if p != path_str]
                findings.append(
                    LintFinding(
                        path=Path(path_str),
                        code="durable-id-duplicate",
                        severity="error",
                        message=f"Duplicate stable ID '{doc_id}' also found in: {', '.join(other_paths)}",
                    )
                )

    # Ownership checks
    if manifest_path is not None:
        if manifest_path.exists():
            try:
                ownership = GeneratedOwnership.load(manifest_path, vault_root)
                for rel_path, entry in ownership.entries.items():
                    target_abs = vault_root / rel_path
                    if not target_abs.exists():
                        findings.append(
                            LintFinding(
                                path=Path(rel_path),
                                code="ownership-file-missing",
                                severity="error",
                                message="Owned generated file is missing from disk.",
                            )
                        )
                        continue

                    try:
                        current_hash = stream_sha256(target_abs)
                        if current_hash != entry.content_hash:
                            findings.append(
                                LintFinding(
                                    path=Path(rel_path),
                                    code="ownership-hash-mismatch",
                                    severity="error",
                                    message="Generated file content hash does not match ownership manifest.",
                                )
                            )
                    except OSError:
                        findings.append(
                            LintFinding(
                                path=Path(rel_path),
                                code="ownership-file-missing",
                                severity="error",
                                message="Failed to read generated file for hash verification.",
                            )
                        )
            except ManifestError as e:
                # manifest loading failed
                rel_manifest = (
                    manifest_path.relative_to(vault_root)
                    if manifest_path.is_relative_to(vault_root)
                    else manifest_path
                )
                findings.append(
                    LintFinding(
                        path=rel_manifest,
                        code="ownership-manifest-invalid",
                        severity="error",
                        message=f"Failed to load ownership manifest: {e}",
                    )
                )

    # Final sorting
    findings.sort(key=_sort_key)

    error_count = sum(1 for f in findings if f.severity == "error")
    warning_count = sum(1 for f in findings if f.severity == "warning")
    suggestion_count = sum(1 for f in findings if f.severity == "suggestion")

    return LintResult(
        findings=tuple(findings),
        error_count=error_count,
        warning_count=warning_count,
        suggestion_count=suggestion_count,
    )
