"""Set-wise stable-identity reconciliation for registry scans.

This module layers the LIFEOS-1643 coherence semantics over the historical file-tracking
helpers. It deliberately keeps the existing ``_hash_file`` seam for unscoped local scans so
streaming, fault-injection, and change-during-read behavior remain covered by the older registry
tests. Both local and externally scoped observations now use no-follow descriptor-pinned reads;
the scoped path additionally supports presence-only observations for denied content.
"""

from __future__ import annotations

import hashlib
import os
import stat
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
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


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
    relative_path = entry.path.as_posix()
    return (
        entry.file_type == ".md"
        and first_root != "proposals"
        and relative_path != "AGENTS.md"
    )


def _capture_for(entry: VaultFile) -> _base._HashCapture:
    if _participates_in_stable_note_identity(entry):
        return _base._HashCapture()
    capture = _base._HashCapture()
    capture.chunks = cast(Any, _DiscardingChunks())
    return capture


def _descriptor_identity(fd: int) -> tuple[int, int]:
    observed = os.fstat(fd)
    return observed.st_dev, observed.st_ino


def _revalidate_scoped_path(
    vault_root: Path,
    parts: tuple[str, ...],
    *,
    expected_chain: tuple[tuple[int, int], ...],
) -> None:
    """Rewalk a scoped path and prove it still names the descriptor chain that was read."""
    opened_fds: list[int] = []
    try:
        current_fd = os.open(vault_root, _DIRECTORY_FLAGS)
        opened_fds.append(current_fd)
        observed_chain = [_descriptor_identity(current_fd)]

        for part in parts[:-1]:
            current_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            opened_fds.append(current_fd)
            observed_chain.append(_descriptor_identity(current_fd))

        current_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=current_fd)
        opened_fds.append(current_fd)
        final_stat = os.fstat(current_fd)
        if not stat.S_ISREG(final_stat.st_mode):
            raise OSError("scoped registry path no longer names a regular file")
        observed_chain.append((final_stat.st_dev, final_stat.st_ino))
    except OSError as exc:
        raise _base.FileTrackingError(
            f"File {vault_root / Path(*parts)} changed during scoped hashing."
        ) from exc
    finally:
        for fd in reversed(opened_fds):
            os.close(fd)

    if tuple(observed_chain) != expected_chain:
        raise _base.FileTrackingError(
            f"File {vault_root / Path(*parts)} changed during scoped hashing."
        )


def _safe_scoped_hash_file(
    vault_root: Path,
    entry: VaultFile,
    *,
    capture: _base._HashCapture,
) -> str:
    """Hash one scoped file from a vault-root descriptor without following symlinks."""
    parts = entry.path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise _base.FileTrackingError(
            f"Could not safely hash scoped registry path {entry.path.as_posix()!r}."
        )

    try:
        root_fd = os.open(vault_root, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise _base.FileTrackingError(
            f"Could not safely open registry vault root {vault_root}: {exc}"
        ) from exc

    current_fd = root_fd
    file_fd: int | None = None
    identity_chain = [_descriptor_identity(root_fd)]
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as exc:
                raise _base.FileTrackingError(
                    "Could not safely traverse scoped registry path "
                    f"{entry.path.as_posix()!r}: {exc}"
                ) from exc
            identity_chain.append(_descriptor_identity(next_fd))
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd

        try:
            file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=current_fd)
            before = os.fstat(file_fd)
        except OSError as exc:
            raise _base.FileTrackingError(
                f"Could not safely open scoped registry file {entry.path.as_posix()!r}: {exc}"
            ) from exc
        if not stat.S_ISREG(before.st_mode):
            raise _base.FileTrackingError(
                f"Scoped registry entry is not a regular file: {entry.path.as_posix()}"
            )
        identity_chain.append((before.st_dev, before.st_ino))

        hasher = hashlib.sha256()
        total_bytes = 0
        try:
            while True:
                chunk = os.read(file_fd, 65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                hasher.update(chunk)
                capture.chunks.append(chunk)
            after = os.fstat(file_fd)
        except OSError as exc:
            raise _base.FileTrackingError(
                f"Could not safely read scoped registry file {entry.path.as_posix()!r}: {exc}"
            ) from exc

        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or before.st_size != after.st_size
            or total_bytes != after.st_size
        ):
            raise _base.FileTrackingError(
                f"File {vault_root / entry.path} changed during scoped hashing."
            )

        _revalidate_scoped_path(
            vault_root,
            parts,
            expected_chain=tuple(identity_chain),
        )
        capture.size_bytes = after.st_size
        capture.mtime_ns = after.st_mtime_ns
        return hasher.hexdigest()
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)


def _prepare_scan_entry(
    vault_root: Path,
    entry: VaultFile,
    *,
    observe_content: bool = True,
    descriptor_safe: bool = False,
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
    if descriptor_safe:
        content_hash = _safe_scoped_hash_file(vault_root, entry, capture=capture)
    else:
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
    scoped = identity_allow_path is not None
    for entry in entries:
        path_str = entry.path.as_posix()
        observe_content = identity_allow_path is None or identity_allow_path(path_str)
        facts = _prepare_scan_entry(
            vault_root,
            entry,
            observe_content=observe_content,
            descriptor_safe=scoped and observe_content,
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
    Authorized scoped paths are opened through vault-root descriptors with no-follow semantics.
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
            deferred_stable_ids: set[str] = set()
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
                if identity_allow_path is None and len(rows) > 1:
                    # An unrestricted refresh is the trusted consolidation boundary. Prefer the
                    # oldest durable row so provenance attached before a scoped visibility change
                    # follows the identity, then park any provisional exact-path occupant below.
                    row = rows[0]
                elif exact_rows:
                    row = exact_rows[0]
                elif len(scoped_rows) > 1:
                    raise _base.FileTrackingError(
                        f"Stable note id {durable_id!r} is ambiguous in scoped registry state."
                    )
                elif not scoped_rows:
                    if identity_allow_path is not None and rows:
                        hidden_path_still_present = any(
                            _canonical_path_from_storage(str(candidate["vault_path"])) in seen
                            for candidate in rows
                        )
                        if not hidden_path_still_present:
                            # The trusted identity's previous path disappeared while exactly one
                            # caller-visible note now claims the ID. That may be a cross-scope
                            # relocation, so preserve the trusted row and keep the visible
                            # observation provisional until an unrestricted refresh can prove it.
                            deferred_stable_ids.add(durable_id)
                        # If a denied prior path is still present, this is a separate hidden note,
                        # not evidence that it relocated. It must not influence the caller-visible
                        # identity decision, so the visible row may retain the same scoped ID.
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
                stored_entry_stable_id = (
                    None
                    if identity_allow_path is not None
                    and entry_stable_id is not None
                    and entry_stable_id in deferred_stable_ids
                    else entry_stable_id
                )

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
                            stored_entry_stable_id if identity_observed else None,
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
                    stored_entry_stable_id
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