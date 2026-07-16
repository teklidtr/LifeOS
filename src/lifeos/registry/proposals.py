"""Git-tracked proposal indexing into the registry."""

from __future__ import annotations

from pathlib import Path

import sqlite3
from dataclasses import dataclass
from typing import Mapping

from lifeos.proposals.loader import load_proposal_directory
from lifeos.proposals.schema import ProposalMetadata, ProposalStatus
from lifeos.registry._registry import Registry, RegistryError
from lifeos.scanner.git import git_tracked_proposal_paths

class ProposalScanError(RuntimeError):
    """Raised when proposal scanning or indexing fails."""

class ProposalQueryError(RegistryError):
    """Raised when proposal registry querying or row conversion fails."""

@dataclass(frozen=True)
class ProposalSummary:
    id: str
    status: ProposalStatus
    title: str
    created_at: str
    updated_at: str

def list_proposals(
    connection: sqlite3.Connection,
    *,
    status: ProposalStatus | None = None,
) -> tuple[ProposalSummary, ...]:
    """
    Return summaries from the disposable SQLite index.
    """
    query = "SELECT id, status, title, created_at, updated_at FROM proposals"
    params: tuple[str, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status.value,)

    query += " ORDER BY updated_at DESC, id ASC"

    try:
        rows = connection.execute(query, params).fetchall()
    except sqlite3.Error as e:
        raise ProposalQueryError("Failed to execute proposal list query") from e

    summaries = []
    for row in rows:
        row_id, row_status, row_title, row_created, row_updated = row
        try:
            parsed_status = ProposalStatus(row_status)
        except ValueError as e:
            raise ProposalQueryError("Invalid status value in database") from e

        summaries.append(ProposalSummary(
            id=row_id,
            status=parsed_status,
            title=row_title,
            created_at=row_created,
            updated_at=row_updated,
        ))

    return tuple(summaries)


def count_proposals_by_status(
    connection: sqlite3.Connection,
) -> Mapping[ProposalStatus, int]:
    """
    Return the aggregate count of tracked proposals grouped by their current status.
    """
    query = "SELECT status, COUNT(1) FROM proposals GROUP BY status"
    try:
        rows = connection.execute(query).fetchall()
    except sqlite3.Error as e:
        raise ProposalQueryError("Failed to execute proposal counts query") from e

    counts = {}
    for row in rows:
        row_status, count = row
        try:
            parsed_status = ProposalStatus(row_status)
        except ValueError as e:
            raise ProposalQueryError("Invalid status value in database") from e
        counts[parsed_status] = count

    ordered_counts = {}
    for auth_status in ProposalStatus:
        if auth_status in counts:
            ordered_counts[auth_status] = counts[auth_status]

    return ordered_counts


def derive_proposal_updated_at(metadata: ProposalMetadata) -> str:
    """
    Derive the updated_at timestamp by selecting the maximum non-null
    lifecycle timestamp. String comparison is safe because ISO 8601
    UTC strings are lexicographically sortable.
    """
    timestamps = [
        metadata.created_at,
        metadata.submitted_at,
        metadata.approved_at,
        metadata.rejected_at,
        metadata.applied_at,
    ]
    return max(t for t in timestamps if t is not None)


def register_proposals_scan(registry: Registry, *, vault_root: Path) -> None:
    """
    Scan all Git-tracked proposals, validate them, and refresh the registry
    proposals table transactionally.
    """
    try:
        tracked_paths = git_tracked_proposal_paths(vault_root)
    except Exception as e:
        raise ProposalScanError(f"Failed to discover tracked proposals: {e}") from e

    proposals_root = vault_root / "proposals"
    rows = []

    for rel_path in tracked_paths:
        proposal_dir = vault_root / rel_path.parent

        if not proposal_dir.exists() or not (proposal_dir / "proposal.md").exists():
            raise ProposalScanError(f"Tracked proposal missing from working tree: {rel_path}")

        res = load_proposal_directory(proposal_dir, proposals_root=proposals_root)

        if any(f.severity == "error" for f in res.findings):
            errors = [f.message for f in res.findings if f.severity == "error"]
            raise ProposalScanError(f"Malformed proposal at {rel_path}: {errors}")

        if not res.proposal:
            raise ProposalScanError(f"Failed to load proposal at {rel_path}")

        meta = res.proposal.metadata
        updated_at = derive_proposal_updated_at(meta)
        rows.append((
            meta.id,
            meta.status.value,
            meta.title,
            meta.created_at,
            updated_at,
        ))

    # Deterministic order by ID (already ordered by path which implies ordered by ID)
    rows.sort(key=lambda r: r[0])

    with registry.connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM proposals")
            if rows:
                conn.executemany(
                    """
                    INSERT INTO proposals (id, status, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.execute("COMMIT")
        except Exception as e:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ProposalScanError(f"Failed to update registry: {e}") from e
