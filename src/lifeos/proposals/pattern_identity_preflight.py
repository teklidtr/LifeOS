"""Canonical personal-pattern identity checks layered over coherent proposal preflight."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .coherence_validation import preflight_proposal as _coherent_preflight_proposal
from .loader import LoadedProposal
from .validation import OperationPreflightResult, PreflightFinding, ProposalPreflightResult


def preflight_proposal(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
    max_inspection_bytes: int = 5 * 1024 * 1024,
    runtime_dir: Path | None = None,
) -> ProposalPreflightResult:
    """Add canonical pattern-ID uniqueness to the ordinary coherent preflight.

    Application invokes this callable while holding the global vault mutation lock, so a
    create-pattern proposal cannot race another canonical pattern creation after validation.
    Public/local preflight gets the same fail-closed invariant without exposing the hidden path
    that owns a colliding identity.
    """
    base = _coherent_preflight_proposal(
        proposal,
        vault_root=vault_root,
        max_inspection_bytes=max_inspection_bytes,
        runtime_dir=runtime_dir,
    )
    if base.state != "valid":
        return base

    candidates, candidate_findings = _candidate_pattern_identities(
        proposal,
        vault_root=vault_root,
    )
    if candidate_findings:
        return _append_findings(base, candidate_findings)
    if not candidates:
        return base

    return _append_findings(
        base,
        _canonical_identity_findings(candidates, vault_root=vault_root),
    )


def _candidate_pattern_identities(
    proposal: LoadedProposal,
    *,
    vault_root: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[PreflightFinding, ...]]]:
    # Keep the personal-pattern package out of proposal import initialization. This module is
    # wired after normal proposal imports, and the concrete parser is needed only at runtime.
    from lifeos.patterns.artifact import parse_pattern
    from lifeos.patterns.contracts import PatternError

    candidates: dict[str, tuple[str, str]] = {}
    findings: dict[str, tuple[PreflightFinding, ...]] = {}
    for operation in proposal.patch_document.operations:
        target_path = operation.target_path
        if (
            operation.op != "create_file"
            or not target_path.startswith("patterns/")
            or not target_path.casefold().endswith(".md")
        ):
            continue
        new_content = getattr(operation, "new_content", None)
        if not isinstance(new_content, str):
            continue
        try:
            artifact = parse_pattern(
                vault_root / target_path,
                target_path,
                new_content,
            )
        except PatternError:
            findings[operation.id] = (
                PreflightFinding(
                    severity="error",
                    code="pattern_candidate_invalid",
                    operation_id=operation.id,
                    target_path=target_path,
                    field_path="new_content",
                    message="Canonical personal-pattern candidate could not be validated safely.",
                ),
            )
            continue
        if artifact is None:
            continue
        candidates[operation.id] = (target_path, artifact.metadata.pattern_id)
    return candidates, findings


def _canonical_identity_findings(
    candidates: dict[str, tuple[str, str]],
    *,
    vault_root: Path,
) -> dict[str, tuple[PreflightFinding, ...]]:
    from lifeos.patterns.artifact import PatternArtifactService
    from lifeos.patterns.contracts import PatternError

    try:
        existing = PatternArtifactService(vault_root=vault_root).list()
    except PatternError:
        return {
            operation_id: (
                _identity_finding(
                    operation_id=operation_id,
                    target_path=target_path,
                    code="pattern_identity_ambiguous",
                    message="Canonical personal-pattern identity state is ambiguous.",
                ),
            )
            for operation_id, (target_path, _pattern_id) in candidates.items()
        }

    existing_ids = {artifact.metadata.pattern_id: artifact.path for artifact in existing}
    candidate_counts: dict[str, int] = {}
    for _target_path, pattern_id in candidates.values():
        candidate_counts[pattern_id] = candidate_counts.get(pattern_id, 0) + 1

    findings: dict[str, tuple[PreflightFinding, ...]] = {}
    for operation_id, (target_path, pattern_id) in candidates.items():
        operation_findings: list[PreflightFinding] = []
        existing_path = existing_ids.get(pattern_id)
        if existing_path is not None and existing_path != target_path:
            operation_findings.append(
                _identity_finding(
                    operation_id=operation_id,
                    target_path=target_path,
                    code="pattern_identity_conflict",
                    message="Canonical personal-pattern identity already exists.",
                )
            )
        if candidate_counts[pattern_id] > 1:
            operation_findings.append(
                _identity_finding(
                    operation_id=operation_id,
                    target_path=target_path,
                    code="pattern_identity_duplicate_candidate",
                    message=(
                        "Proposal creates more than one canonical personal pattern with the same "
                        "identity."
                    ),
                )
            )
        if operation_findings:
            findings[operation_id] = tuple(operation_findings)
    return findings


def _identity_finding(
    *,
    operation_id: str,
    target_path: str,
    code: str,
    message: str,
) -> PreflightFinding:
    return PreflightFinding(
        severity="error",
        code=code,
        operation_id=operation_id,
        target_path=target_path,
        field_path="new_content.pattern_id",
        message=message,
    )


def _append_findings(
    base: ProposalPreflightResult,
    findings_by_operation: dict[str, tuple[PreflightFinding, ...]],
) -> ProposalPreflightResult:
    if not findings_by_operation:
        return base

    operations: list[OperationPreflightResult] = []
    for operation in base.operations:
        extra = findings_by_operation.get(operation.operation_id)
        if extra is None:
            operations.append(operation)
            continue
        operations.append(
            replace(
                operation,
                state="invalid",
                findings=(*operation.findings, *extra),
            )
        )
    return replace(base, state="invalid", operations=tuple(operations))
