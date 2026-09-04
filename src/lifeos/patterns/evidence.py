"""Deterministic evidence lineage and factual source-state diagnostics for patterns."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from lifeos.registry import Registry

from .contracts import EvidenceRole, PatternEvidence

EvidenceState = Literal["unchanged", "moved", "changed", "missing", "ambiguous", "deleted"]
EvidencePathPredicate = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class NormalizedEvidenceReference:
    """Canonical fingerprint contribution for one reviewed evidence reference."""

    role: EvidenceRole
    source_id: str | None
    path: str
    content_hash: str
    observation_id: str | None
    event_id: str | None

    def sort_key(self) -> tuple[str, str, str, str, str, str]:
        """Return an ordering key that keeps absent optional identities deterministic."""
        return (
            self.role,
            self.source_id or "",
            self.path,
            self.content_hash,
            self.observation_id or "",
            self.event_id or "",
        )

    def canonical_tuple(self) -> tuple[str | None, ...]:
        """Return the DD-095 normalized tuple encoded into the fingerprint payload."""
        return (
            self.role,
            self.source_id,
            self.path,
            self.content_hash,
            self.observation_id,
            self.event_id,
        )


@dataclass(frozen=True, slots=True)
class PatternEvidenceDiagnostic:
    """Factual current-state diagnostic for one immutable reviewed reference."""

    reference: PatternEvidence
    state: EvidenceState
    current_path: str | None = None
    current_content_hash: str | None = None
    candidate_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RegistryEvidenceRow:
    path: str
    content_hash: str | None
    is_deleted: bool


def normalize_evidence_reference(reference: PatternEvidence) -> NormalizedEvidenceReference:
    """Normalize one already-validated pattern evidence reference without advancing it."""
    return NormalizedEvidenceReference(
        role=reference.role,
        source_id=reference.source_id,
        path=reference.path,
        content_hash=reference.content_hash,
        observation_id=reference.observation_id,
        event_id=reference.event_id,
    )


def compute_evidence_fingerprint(references: Iterable[PatternEvidence]) -> str:
    """Hash the unique normalized reviewed references independent of input ordering."""
    normalized = {normalize_evidence_reference(reference) for reference in references}
    ordered = sorted(normalized, key=NormalizedEvidenceReference.sort_key)
    payload = [reference.canonical_tuple() for reference in ordered]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rows_for_reference(
    connection: sqlite3.Connection,
    reference: PatternEvidence,
    *,
    allow_path: EvidencePathPredicate,
) -> tuple[_RegistryEvidenceRow, ...]:
    if reference.source_id is not None:
        rows = connection.execute(
            """
            SELECT vault_path, content_hash, is_deleted
            FROM files
            WHERE stable_id = ?
            ORDER BY is_deleted, vault_path
            """,
            (reference.source_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT vault_path, content_hash, is_deleted
            FROM files
            WHERE vault_path = ?
            ORDER BY is_deleted, vault_path
            """,
            (reference.path,),
        ).fetchall()

    visible: list[_RegistryEvidenceRow] = []
    for row in rows:
        path = str(row["vault_path"])
        if not allow_path(path):
            continue
        visible.append(
            _RegistryEvidenceRow(
                path=path,
                content_hash=None if row["content_hash"] is None else str(row["content_hash"]),
                is_deleted=bool(row["is_deleted"]),
            )
        )
    return tuple(visible)


def _pattern_hash(registry_hash: str | None) -> str | None:
    if registry_hash is None:
        return None
    if registry_hash.startswith("sha256:"):
        return registry_hash
    return "sha256:" + registry_hash


def _diagnose_reference(
    connection: sqlite3.Connection,
    reference: PatternEvidence,
    *,
    allow_path: EvidencePathPredicate,
) -> PatternEvidenceDiagnostic:
    rows = _rows_for_reference(connection, reference, allow_path=allow_path)
    active = tuple(row for row in rows if not row.is_deleted)

    if len(active) > 1:
        return PatternEvidenceDiagnostic(
            reference=reference,
            state="ambiguous",
            candidate_paths=tuple(sorted(row.path for row in active)),
        )

    if active:
        current = active[0]
        current_hash = _pattern_hash(current.content_hash)
        if current_hash == reference.content_hash:
            state: EvidenceState = (
                "moved"
                if reference.source_id is not None and current.path != reference.path
                else "unchanged"
            )
        else:
            state = "changed"
        return PatternEvidenceDiagnostic(
            reference=reference,
            state=state,
            current_path=current.path,
            current_content_hash=current_hash,
        )

    if any(row.is_deleted for row in rows):
        return PatternEvidenceDiagnostic(reference=reference, state="deleted")
    return PatternEvidenceDiagnostic(reference=reference, state="missing")


def resolve_evidence_states(
    registry: Registry,
    references: Iterable[PatternEvidence],
    *,
    allow_path: EvidencePathPredicate,
) -> tuple[PatternEvidenceDiagnostic, ...]:
    """Resolve factual state within the caller-authorized path scope without advancing reviews."""
    reviewed = tuple(references)
    with registry.connect_read_only() as connection:
        return tuple(
            _diagnose_reference(connection, reference, allow_path=allow_path)
            for reference in reviewed
        )
