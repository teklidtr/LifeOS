"""Register scanned files into the registry."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from collections.abc import Iterable

from lifeos.registry._registry import Registry
from lifeos.scanner import VaultFile

__all__ = [
    "FileComparison",
    "FileRegistrationState",
    "FileTrackingError",
    "ScanResult",
    "compare_registered_file",
    "hash_file_content",
    "register_scan",
]


class FileTrackingError(RuntimeError):
    """Raised when file tracking fails."""


class FileRegistrationState(str, Enum):
    REGISTERED_UNCHANGED = "registered_unchanged"
    REGISTERED_MODIFIED = "registered_modified"
    REGISTERED_MISSING = "registered_missing"
    UNREGISTERED_PRESENT = "unregistered_present"
    UNREGISTERED_MISSING = "unregistered_missing"


@dataclass(frozen=True, slots=True)
class FileComparison:
    path: str
    state: FileRegistrationState
    registry_hash: str | None
    working_tree_hash: str | None


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The outcome of registering a vault scan."""

    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)



def _hash_chunks(chunks: Iterable[bytes]) -> str:
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.hexdigest()


def hash_file_content(content: bytes) -> str:
    """Hash byte content for canonical registry representation."""
    return _hash_chunks((content,))


def _hash_file(path: Path) -> str:
    try:
        stat_before = path.stat()
    except OSError as exc:
        raise FileTrackingError(f"Could not read metadata for {path}: {exc}") from exc

    try:
        with open(path, "rb") as f:
            content_hash = _hash_chunks(iter(lambda: f.read(65536), b""))
    except OSError as exc:
        raise FileTrackingError(f"Could not read {path}: {exc}") from exc

    try:
        stat_after = path.stat()
    except OSError as exc:
        raise FileTrackingError(f"Could not read metadata for {path}: {exc}") from exc

    if (
        stat_before.st_mtime_ns != stat_after.st_mtime_ns
        or stat_before.st_size != stat_after.st_size
    ):
        raise FileTrackingError(f"File {path} changed during hashing.")

    return content_hash


def validate_vault_path(vault_path: str) -> None:
    if not vault_path:
        raise FileTrackingError("Vault path cannot be empty.")
    if "\0" in vault_path:
        raise FileTrackingError("Vault path cannot contain NUL characters.")
    if "\\" in vault_path:
        raise FileTrackingError("Vault path cannot contain backslashes.")

    path = PurePosixPath(vault_path)
    if path.is_absolute():
        raise FileTrackingError(f"Vault path cannot be absolute: {vault_path}")

    for part in path.parts:
        if part in (".", ".."):
            raise FileTrackingError(f"Vault path cannot contain dot components: {vault_path}")

    if str(path) != vault_path:
        raise FileTrackingError(f"Vault path is not normalized: {vault_path}")


def compare_registered_file(
    registry: Registry, vault_path: str, working_tree_hash: str | None
) -> FileComparison:
    """Compare a file's working tree hash against the registry read-only."""
    validate_vault_path(vault_path)

    if working_tree_hash is not None:
        if len(working_tree_hash) != 64 or not re.fullmatch(r"[0-9a-f]{64}", working_tree_hash):
            raise FileTrackingError("Working tree hash must be exactly 64 lowercase hexadecimal characters.")

    with registry.connect_read_only() as conn:
        row = conn.execute(
            "SELECT content_hash, is_deleted FROM files WHERE vault_path = ?", (vault_path,)
        ).fetchone()

        if row is None or row["is_deleted"] == 1:
            if working_tree_hash is not None:
                state = FileRegistrationState.UNREGISTERED_PRESENT
            else:
                state = FileRegistrationState.UNREGISTERED_MISSING
            registry_hash = None
        else:
            registry_hash = row["content_hash"]
            if working_tree_hash is None:
                state = FileRegistrationState.REGISTERED_MISSING
            elif registry_hash == working_tree_hash:
                state = FileRegistrationState.REGISTERED_UNCHANGED
            else:
                state = FileRegistrationState.REGISTERED_MODIFIED

        return FileComparison(
            path=vault_path,
            state=state,
            registry_hash=registry_hash,
            working_tree_hash=working_tree_hash,
        )


def register_scan(registry: Registry, vault_root: Path, entries: list[VaultFile]) -> ScanResult:
    """Hash and register scanned files into the registry database."""
    seen = set()
    for entry in entries:
        path_str = str(entry.path)
        if path_str in seen:
            raise FileTrackingError(f"Duplicate normalized path in scan entries: {path_str}")
        seen.add(path_str)

    new_paths = []
    modified_paths = []
    unchanged_paths = []
    deleted_paths = []

    with registry.connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                """
                CREATE TEMP TABLE seen_paths (
                    vault_path TEXT PRIMARY KEY
                )
                """
            )

            now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

            for entry in entries:
                path_str = str(entry.path)
                full_path = vault_root / entry.path

                content_hash = _hash_file(full_path)

                try:
                    stat = full_path.stat()
                except OSError as exc:
                    raise FileTrackingError(
                        f"Could not read metadata for {full_path}: {exc}"
                    ) from exc

                mtime_ns = stat.st_mtime_ns
                size_bytes = stat.st_size

                conn.execute("INSERT INTO seen_paths (vault_path) VALUES (?)", (path_str,))

                row = conn.execute(
                    "SELECT content_hash, is_deleted FROM files WHERE vault_path = ?", (path_str,)
                ).fetchone()

                if row is None:
                    conn.execute(
                        f"""
                        INSERT INTO files (
                            vault_path, file_kind, content_hash, size_bytes, mtime_ns,
                            first_seen_at, last_seen_at, is_deleted
                        ) VALUES (?, ?, ?, ?, ?, {now_expr}, {now_expr}, 0)
                        """,
                        (path_str, entry.file_type, content_hash, size_bytes, mtime_ns),
                    )
                    new_paths.append(path_str)
                else:
                    db_hash = row["content_hash"]
                    is_deleted = row["is_deleted"]

                    if is_deleted == 1 or db_hash != content_hash:
                        conn.execute(
                            f"""
                            UPDATE files 
                            SET content_hash = ?, size_bytes = ?, mtime_ns = ?,
                                last_seen_at = {now_expr}, is_deleted = 0
                            WHERE vault_path = ?
                            """,
                            (content_hash, size_bytes, mtime_ns, path_str),
                        )
                        modified_paths.append(path_str)
                    else:
                        conn.execute(
                            f"""
                            UPDATE files
                            SET last_seen_at = {now_expr}
                            WHERE vault_path = ?
                            """,
                            (path_str,),
                        )
                        unchanged_paths.append(path_str)

            cursor = conn.execute(
                """
                SELECT vault_path FROM files 
                WHERE is_deleted = 0 
                AND NOT EXISTS (
                    SELECT 1 FROM seen_paths WHERE seen_paths.vault_path = files.vault_path
                )
                """
            )
            for row in cursor.fetchall():
                deleted_paths.append(row["vault_path"])

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

            conn.execute("DROP TABLE seen_paths")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    return ScanResult(
        new=sorted(new_paths),
        modified=sorted(modified_paths),
        unchanged=sorted(unchanged_paths),
        deleted=sorted(deleted_paths),
    )
