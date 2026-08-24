"""Set-wise stable-identity reconciliation for registry scans.

This module layers the LIFEOS-1643 coherence semantics over the historical file-tracking
helpers. It deliberately keeps the existing ``_hash_file`` seam so streaming, fault-injection,
and change-during-read behavior remain covered by the older registry tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry import file_tracking as _base
from lifeos.registry._registry import Registry
from lifeos.scanner import VaultFile


@dataclass(frozen=True, slots=True)
class _PreparedScanEntry:
    stable_id: str | None
    content_hash: str
    size_bytes: int
    mtime_ns: int


class _DiscardingChunks:
    """List-shaped sink used to retain hash metadata without retaining attachment bytes."""

    def append(self, _chunk: bytes) -> None:
        return None


def _participates_in_stable_note_identity(entry: VaultFile) -> bool:
    first_root = entry.path.parts[0] if entry.path.parts else ""
    return entry.file_type == ".md" and first_root != "proposals"


def _capture_for(entry: VaultFile) -> _base._HashCapture:
    if _participates_in_stable_note_identity(entry):
        return _base._HashCapture()
    capture = _base._HashCapture()
    capture.chunks = cast(Any, _DiscardingChunks())
    return capture


def _prepare_scan_entry(vault_root: Path, entry: VaultFile) -> _PreparedScanEntry:
    full_path = vault_root / entry.path
    capture = _capture_for(entry)
    content_hash = _base._hash_file(full_path, capture=capture)
    if capture.size_bytes is None or capture.mtime_ns is None:
        raise _base.FileTrackingError(f"Could not capture registry metadata for {full_path}.")

    stable_id: str | None = None
    if _participates_in_stable_note_identity(entry):
        content = b"".join(capture.chunks)
        if len(content) != capture.size_bytes:
            raise _base.FileTrackingError(f"File {full_path} changed during hashing.")
        try:
            text = content.decode("utf-8")
        except UnicodeError as exc:
            raise _base.FileTrackingError(
                f"Could not inspect Markdown identity for {full_path}: {exc}"
            ) from exc
        parsed = parse_markdown_note(full_path, content=text)
        parsed_id = parsed.durable_fields.id
        if parsed_id is not None:
            stable_id = parsed_id.strip() or None

    return _PreparedScanEntry(
        stable_id=stable_id,
        content_hash=content_hash,
        size_bytes=capture.size_bytes,
        mtime_ns=capture.mtime_ns,
    )


def _prepare_scan_entries(
    vault_root: Path,
    entries: list[VaultFile],
) -> dict[str, _PreparedScanEntry]:
    prepared: dict[str, _PreparedScanEntry] = {}
    id_paths: dict[str, list[str]] = {}
    for entry in entries:
        path_str = entry.path.as_posix()
        facts = _prepare_scan_entry(vault_root, entry)
        prepared[path_str] = facts
        if facts.stable_id is not None:
            id_paths.setdefault(facts.stable_id, []).append(path_str)

    duplicates = {stable_id: paths for stable_id, paths in id_paths.items() if len(paths) > 1}
    if duplicates:
        details = "; ".join(
            f"{stable_id!r}: {', '.join(sorted(paths))}"
            for stable_id, paths in sorted(duplicates.items())
        )
        raise _base.FileTrackingError(
            "Ambiguous stable note id(s) in canonical Markdown; registry refresh aborted: " + details
        )
    return prepared


def _parking_path(row_id: int) -> str:
    return f".lifeos/registry-tombstones/{row_id}/reserved"


def _park_row(conn: Any, *, row_id: int, now_expr: str) -> None:
    """Move one historical row out of the live path namespace without losing its identity."""
    conn.execute(
        f"""
        UPDATE files
        SET vault_path = ?, is_deleted = 1, last_seen_at = {now_expr}
        WHERE id = ?
        """,
        (_parking_path(row_id), row_id),
    )


def register_scan(registry: Registry, vault_root: Path, entries: list[VaultFile]) -> _base.ScanResult:
    """Register a complete scan while reconciling stable identities as one transaction.

    All identity relocations are reserved before any final path is assigned. That makes swaps
    and longer cycles safe: each surviving stable identity keeps the same ``files.id`` and thus
    retains every foreign-keyed provenance/source-version relationship. A confirmed-deleted
    path may be reused by a different identity because the historical row is moved into the
    disposable tombstone namespace instead of being rewritten into the new note.
    """
    seen: set[str] = set()
    for entry in entries:
        path_str = entry.path.as_posix()
        if path_str in seen:
            raise _base.FileTrackingError(
                f"Duplicate normalized path in scan entries: {path_str}"
            )
        seen.add(path_str)

    prepared = _prepare_scan_entries(vault_root, entries)
    new_paths: list[str] = []
    modified_paths: list[str] = []
    unchanged_paths: list[str] = []
    deleted_paths: list[str] = []
    renamed_paths: list[tuple[str, str]] = []

    with registry.connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DROP TABLE IF EXISTS temp.seen_paths")
            conn.execute(
                "CREATE TEMP TABLE seen_paths (vault_path TEXT PRIMARY KEY NOT NULL)"
            )
            for path_str in sorted(seen):
                conn.execute("INSERT INTO seen_paths (vault_path) VALUES (?)", (path_str,))

            now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

            current_targets = {
                facts.stable_id: path
                for path, facts in prepared.items()
                if facts.stable_id is not None
            }
            relocations: dict[str, tuple[int, str, str | None, int]] = {}
            for durable_id, target_path in sorted(current_targets.items()):
                row = conn.execute(
                    """
                    SELECT id, vault_path, stable_id, content_hash, is_deleted
                    FROM files WHERE stable_id = ?
                    """,
                    (durable_id,),
                ).fetchone()
                if row is None:
                    continue
                old_path = str(row["vault_path"])
                if old_path != target_path:
                    relocations[durable_id] = (
                        int(row["id"]),
                        old_path,
                        str(row["content_hash"]) if row["content_hash"] is not None else None,
                        int(row["is_deleted"]),
                    )

            for row_id, _old_path, _old_hash, _was_deleted in relocations.values():
                _park_row(conn, row_id=row_id, now_expr=now_expr)

            for entry in entries:
                path_str = entry.path.as_posix()
                facts = prepared[path_str]
                entry_stable_id = facts.stable_id
                content_hash = facts.content_hash
                mtime_ns = facts.mtime_ns
                size_bytes = facts.size_bytes

                relocation = (
                    relocations.get(entry_stable_id)
                    if entry_stable_id is not None
                    else None
                )
                if relocation is not None:
                    moving_id, old_path, previous_hash, was_deleted = relocation
                    occupant = conn.execute(
                        """
                        SELECT id, stable_id, is_deleted
                        FROM files WHERE vault_path = ?
                        """,
                        (path_str,),
                    ).fetchone()
                    if occupant is not None and int(occupant["id"]) != moving_id:
                        occupant_stable_id = occupant["stable_id"]
                        if (
                            occupant_stable_id is not None
                            and str(occupant_stable_id) in current_targets
                        ):
                            raise _base.FileTrackingError(
                                "Registry relocation reservation failed for a surviving stable "
                                f"identity at {path_str}."
                            )
                        _park_row(conn, row_id=int(occupant["id"]), now_expr=now_expr)

                    conn.execute(
                        f"""
                        UPDATE files
                        SET vault_path = ?, file_kind = ?, stable_id = ?, content_hash = ?,
                            size_bytes = ?, mtime_ns = ?, last_seen_at = {now_expr}, is_deleted = 0
                        WHERE id = ?
                        """,
                        (
                            path_str,
                            entry.file_type,
                            entry_stable_id,
                            content_hash,
                            size_bytes,
                            mtime_ns,
                            moving_id,
                        ),
                    )
                    renamed_paths.append((old_path, path_str))
                    if previous_hash != content_hash or was_deleted:
                        modified_paths.append(path_str)
                    continue

                row = conn.execute(
                    """
                    SELECT id, stable_id, content_hash, is_deleted
                    FROM files WHERE vault_path = ?
                    """,
                    (path_str,),
                ).fetchone()

                if row is not None and int(row["is_deleted"]) == 1:
                    old_stable_id = row["stable_id"]
                    if (
                        old_stable_id is not None
                        and entry_stable_id != str(old_stable_id)
                        and _participates_in_stable_note_identity(entry)
                    ):
                        _park_row(conn, row_id=int(row["id"]), now_expr=now_expr)
                        row = None

                if row is None:
                    conn.execute(
                        f"""
                        INSERT INTO files (
                            vault_path, stable_id, file_kind, content_hash, size_bytes, mtime_ns,
                            first_seen_at, last_seen_at, is_deleted
                        ) VALUES (?, ?, ?, ?, ?, ?, {now_expr}, {now_expr}, 0)
                        """,
                        (
                            path_str,
                            entry_stable_id,
                            entry.file_type,
                            content_hash,
                            size_bytes,
                            mtime_ns,
                        ),
                    )
                    new_paths.append(path_str)
                    continue

                existing_stable_id = row["stable_id"]
                if (
                    int(row["is_deleted"]) == 0
                    and existing_stable_id is not None
                    and entry_stable_id != str(existing_stable_id)
                    and _participates_in_stable_note_identity(entry)
                ):
                    raise _base.FileTrackingError(
                        f"Stable note identity changed in place at {path_str}: "
                        f"{existing_stable_id!r} -> {entry_stable_id!r}."
                    )

                db_hash = row["content_hash"]
                is_deleted = int(row["is_deleted"])
                if is_deleted == 1 or db_hash != content_hash:
                    conn.execute(
                        f"""
                        UPDATE files
                        SET stable_id = ?, file_kind = ?, content_hash = ?, size_bytes = ?,
                            mtime_ns = ?, last_seen_at = {now_expr}, is_deleted = 0
                        WHERE id = ?
                        """,
                        (
                            entry_stable_id,
                            entry.file_type,
                            content_hash,
                            size_bytes,
                            mtime_ns,
                            int(row["id"]),
                        ),
                    )
                    modified_paths.append(path_str)
                else:
                    conn.execute(
                        f"""
                        UPDATE files
                        SET stable_id = ?, file_kind = ?, size_bytes = ?, mtime_ns = ?,
                            last_seen_at = {now_expr}
                        WHERE id = ?
                        """,
                        (
                            entry_stable_id,
                            entry.file_type,
                            size_bytes,
                            mtime_ns,
                            int(row["id"]),
                        ),
                    )
                    unchanged_paths.append(path_str)

            cursor = conn.execute(
                """
                SELECT vault_path FROM files
                WHERE is_deleted = 0
                AND NOT EXISTS (
                    SELECT 1 FROM seen_paths WHERE seen_paths.vault_path = files.vault_path
                )
                ORDER BY vault_path
                """
            )
            deleted_paths = [str(row["vault_path"]) for row in cursor.fetchall()]
            if deleted_paths:
                conn.execute(
                    f"""
                    UPDATE files
                    SET is_deleted = 1, last_seen_at = {now_expr}
                    WHERE is_deleted = 0
                    AND NOT EXISTS (
                        SELECT 1 FROM seen_paths WHERE seen_paths.vault_path = files.vault_path
                    )
                    """
                )

            conn.execute("DROP TABLE temp.seen_paths")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return _base.ScanResult(
        new=sorted(new_paths),
        modified=sorted(modified_paths),
        unchanged=sorted(unchanged_paths),
        deleted=sorted(deleted_paths),
        renamed=sorted(renamed_paths),
    )
