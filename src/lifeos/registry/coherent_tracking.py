"""Set-wise stable-identity reconciliation for registry scans.

This module layers the LIFEOS-1643 coherence semantics over the historical file-tracking
helpers. It deliberately keeps the existing ``_hash_file`` seam so streaming, fault-injection,
and change-during-read behavior remain covered by the older registry tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry import file_tracking as _base
from lifeos.registry._registry import Registry
from lifeos.scanner import VaultFile

_TOMBSTONE_PREFIX = ".lifeos/registry-tombstones/"
IdentityPathPredicate = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class _PreparedScanEntry:
    stable_id: str | None
    identity_observed: bool
    content_observed: bool
    content_hash: str | None
    size_bytes: int
    mtime_ns: int | None


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


def _prepare_scan_entry(
    vault_root: Path,
    entry: VaultFile,
    *,
    observe_content: bool = True,
) -> _PreparedScanEntry:
    # Scoped external callers may know a path exists from directory metadata without being
    # authorized to open its content. Preserve that presence fact without hashing or parsing it.
    if not observe_content:
        return _PreparedScanEntry(
            stable_id=None,
            identity_observed=False,
            content_observed=False,
            content_hash=None,
            size_bytes=entry.size_bytes,
            mtime_ns=None,
        )

    full_path = vault_root / entry.path
    identity_observed = _participates_in_stable_note_identity(entry)
    capture = _capture_for(entry)
    content_hash = _base._hash_file(full_path, capture=capture)
    if capture.size_bytes is None or capture.mtime_ns is None:
        raise _base.FileTrackingError(f"Could not capture registry metadata for {full_path}.")

    stable_id: str | None = None
    if identity_observed:
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
        identity_observed=identity_observed,
        content_observed=True,
        content_hash=content_hash,
        size_bytes=capture.size_bytes,
        mtime_ns=capture.mtime_ns,
    )


def _prepare_scan_entries(
    vault_root: Path,
    entries: list[VaultFile],
    *,
    identity_allow_path: IdentityPathPredicate | None = None,
) -> dict[str, _PreparedScanEntry]:
    prepared: dict[str, _PreparedScanEntry] = {}
    id_paths: dict[str, list[str]] = {}
    for entry in entries:
        path_str = entry.path.as_posix()
        observe_content = identity_allow_path is None or identity_allow_path(path_str)
        facts = _prepare_scan_entry(
            vault_root,
            entry,
            observe_content=observe_content,
        )
        prepared[path_str] = facts
        if facts.identity_observed and facts.stable_id is not None:
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


def _canonical_path_from_storage(path: str) -> str:
    """Recover the last canonical path from a disposable parked-row storage key."""
    if not path.startswith(_TOMBSTONE_PREFIX):
        return path
    remainder = path[len(_TOMBSTONE_PREFIX) :]
    _row_id, separator, canonical_path = remainder.partition("/")
    return canonical_path if separator and canonical_path else path


def _parking_path(row_id: int, prior_path: str) -> str:
    canonical_path = _canonical_path_from_storage(prior_path)
    return f"{_TOMBSTONE_PREFIX}{row_id}/{canonical_path}"


def _park_row(conn: Any, *, row_id: int, prior_path: str, now_expr: str) -> None:
    """Move one historical row out of the live path namespace without losing its identity."""
    conn.execute(
        f"""
        UPDATE files
        SET vault_path = ?, is_deleted = 1, last_seen_at = {now_expr}
        WHERE id = ?
        """,
        (_parking_path(row_id, prior_path), row_id),
    )


def _row_allowed_for_identity(
    row: Any,
    *,
    identity_allow_path: IdentityPathPredicate | None,
) -> bool:
    if identity_allow_path is None:
        return True
    canonical_path = _canonical_path_from_storage(str(row["vault_path"]))
    return identity_allow_path(canonical_path)


def register_scan(
    registry: Registry,
    vault_root: Path,
    entries: list[VaultFile],
    *,
    identity_allow_path: IdentityPathPredicate | None = None,
) -> _base.ScanResult:
    """Register a complete scan while reconciling stable identities as one transaction.

    With no scope predicate, canonical files are hashed and stable Markdown IDs are interpreted
    exactly as in the local registry contract. A scoped external caller can deny a path before
    content access: the registry still records filesystem presence, but it neither hashes nor
    parses those bytes. Previously known local identity facts for denied paths are retained for a
    later trusted refresh while being excluded from every scoped ambiguity/relocation decision.
    """
    seen: set[str] = set()
    for entry in entries:
        path_str = entry.path.as_posix()
        if path_str in seen:
            raise _base.FileTrackingError(
                f"Duplicate normalized path in scan entries: {path_str}"
            )
        seen.add(path_str)

    prepared = _prepare_scan_entries(
        vault_root,
        entries,
        identity_allow_path=identity_allow_path,
    )
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
                if facts.identity_observed and facts.stable_id is not None
            }
            relocations: dict[str, tuple[int, str, str | None, int]] = {}
            for durable_id, target_path in sorted(current_targets.items()):
                rows = conn.execute(
                    """
                    SELECT id, vault_path, stable_id, content_hash, is_deleted
                    FROM files WHERE stable_id = ?
                    ORDER BY id
                    """,
                    (durable_id,),
                ).fetchall()
                scoped_rows = [
                    row
                    for row in rows
                    if _row_allowed_for_identity(
                        row,
                        identity_allow_path=identity_allow_path,
                    )
                ]
                exact_rows = [
                    row
                    for row in scoped_rows
                    if _canonical_path_from_storage(str(row["vault_path"])) == target_path
                ]
                if exact_rows:
                    row = exact_rows[0]
                elif len(scoped_rows) > 1:
                    raise _base.FileTrackingError(
                        f"Stable note id {durable_id!r} is ambiguous in scoped registry state."
                    )
                elif not scoped_rows:
                    continue
                else:
                    row = scoped_rows[0]
                stored_path = str(row["vault_path"])
                if _canonical_path_from_storage(stored_path) != target_path:
                    relocations[durable_id] = (
                        int(row["id"]),
                        _canonical_path_from_storage(stored_path),
                        str(row["content_hash"]) if row["content_hash"] is not None else None,
                        int(row["is_deleted"]),
                    )

            for row_id, old_path, _old_hash, _was_deleted in relocations.values():
                _park_row(
                    conn,
                    row_id=row_id,
                    prior_path=old_path,
                    now_expr=now_expr,
                )

            for entry in entries:
                path_str = entry.path.as_posix()
                facts = prepared[path_str]
                entry_stable_id = facts.stable_id
                identity_observed = facts.identity_observed
                content_hash = facts.content_hash
                mtime_ns = facts.mtime_ns
                size_bytes = facts.size_bytes

                relocation = (
                    relocations.get(entry_stable_id)
                    if identity_observed and entry_stable_id is not None
                    else None
                )
                if relocation is not None:
                    moving_id, old_path, previous_hash, was_deleted = relocation
                    occupant = conn.execute(
                        """
                        SELECT id, vault_path, stable_id, is_deleted
                        FROM files WHERE vault_path = ?
                        """,
                        (path_str,),
                    ).fetchone()
                    if occupant is not None and int(occupant["id"]) != moving_id:
                        occupant_stable_id = occupant["stable_id"]
                        if (
                            occupant_stable_id is not None
                            and str(occupant_stable_id) in current_targets
                            and _row_allowed_for_identity(
                                occupant,
                                identity_allow_path=identity_allow_path,
                            )
                        ):
                            raise _base.FileTrackingError(
                                "Registry relocation reservation failed for a surviving stable "
                                f"identity at {path_str}."
                            )
                        _park_row(
                            conn,
                            row_id=int(occupant["id"]),
                            prior_path=path_str,
                            now_expr=now_expr,
                        )

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
                    if old_path != path_str:
                        renamed_paths.append((old_path, path_str))
                    if previous_hash != content_hash or was_deleted:
                        modified_paths.append(path_str)
                    continue

                row = conn.execute(
                    """
                    SELECT id, vault_path, stable_id, content_hash, is_deleted
                    FROM files WHERE vault_path = ?
                    """,
                    (path_str,),
                ).fetchone()

                if not facts.content_observed:
                    if row is None:
                        conn.execute(
                            f"""
                            INSERT INTO files (
                                vault_path, stable_id, file_kind, content_hash, size_bytes,
                                mtime_ns, first_seen_at, last_seen_at, is_deleted
                            ) VALUES (?, NULL, ?, NULL, ?, NULL, {now_expr}, {now_expr}, 0)
                            """,
                            (path_str, entry.file_type, size_bytes),
                        )
                        new_paths.append(path_str)
                    elif int(row["is_deleted"]) == 1:
                        conn.execute(
                            f"""
                            UPDATE files
                            SET file_kind = ?, size_bytes = ?, last_seen_at = {now_expr}, is_deleted = 0
                            WHERE id = ?
                            """,
                            (entry.file_type, size_bytes, int(row["id"])),
                        )
                        modified_paths.append(path_str)
                    else:
                        conn.execute(
                            f"""
                            UPDATE files
                            SET file_kind = ?, size_bytes = ?, last_seen_at = {now_expr}
                            WHERE id = ?
                            """,
                            (entry.file_type, size_bytes, int(row["id"])),
                        )
                        unchanged_paths.append(path_str)
                    continue

                if row is not None and int(row["is_deleted"]) == 1:
                    old_stable_id = row["stable_id"]
                    if (
                        identity_observed
                        and old_stable_id is not None
                        and entry_stable_id != str(old_stable_id)
                    ):
                        _park_row(
                            conn,
                            row_id=int(row["id"]),
                            prior_path=path_str,
                            now_expr=now_expr,
                        )
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
                            entry_stable_id if identity_observed else None,
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
                    identity_observed
                    and int(row["is_deleted"]) == 0
                    and existing_stable_id is not None
                    and entry_stable_id != str(existing_stable_id)
                ):
                    raise _base.FileTrackingError(
                        f"Stable note identity changed in place at {path_str}: "
                        f"{existing_stable_id!r} -> {entry_stable_id!r}."
                    )

                effective_stable_id = (
                    entry_stable_id
                    if identity_observed
                    else (str(existing_stable_id) if existing_stable_id is not None else None)
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
                            effective_stable_id,
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
                            effective_stable_id,
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
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    return _base.ScanResult(
        new=sorted(new_paths),
        modified=sorted(modified_paths),
        unchanged=sorted(unchanged_paths),
        deleted=sorted(deleted_paths),
        renamed=sorted(renamed_paths),
    )
