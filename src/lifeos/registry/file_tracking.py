"""Register scanned files into the registry."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from lifeos.markdown.parser import parse_markdown_note
from lifeos.registry._registry import Registry
from lifeos.scanner import VaultFile

__all__ = [
    "FileComparison",
    "FileRegistrationState",
    "FileTrackingError",
    "RegisteredStableIdentity",
    "ScanResult",
    "compare_registered_file",
    "hash_file_content",
    "list_registered_stable_identities",
    "register_scan",
    "resolve_registered_stable_id",
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
class RegisteredStableIdentity:
    """Disposable stable-id -> current-path -> current-hash registry fact."""

    stable_id: str
    path: str
    content_hash: str | None


@dataclass(frozen=True, slots=True)
class ScanResult:
    """The outcome of registering a vault scan."""

    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)


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


def _stable_id_for_entry(full_path: Path, entry: VaultFile) -> str | None:
    if entry.file_type != ".md":
        return None
    try:
        parsed = parse_markdown_note(full_path)
    except (OSError, UnicodeError) as exc:
        raise FileTrackingError(f"Could not inspect Markdown identity for {full_path}: {exc}") from exc
    stable_id = parsed.durable_fields.id
    if stable_id is None:
        return None
    normalized = stable_id.strip()
    return normalized or None


def _scan_stable_ids(vault_root: Path, entries: list[VaultFile]) -> dict[str, str | None]:
    stable_ids: dict[str, str | None] = {}
    id_paths: dict[str, list[str]] = {}
    for entry in entries:
        path_str = str(entry.path)
        stable_id = _stable_id_for_entry(vault_root / entry.path, entry)
        stable_ids[path_str] = stable_id
        if stable_id is not None:
            id_paths.setdefault(stable_id, []).append(path_str)

    duplicates = {stable_id: paths for stable_id, paths in id_paths.items() if len(paths) > 1}
    if duplicates:
        details = "; ".join(
            f"{stable_id!r}: {', '.join(sorted(paths))}"
            for stable_id, paths in sorted(duplicates.items())
        )
        raise FileTrackingError(
            "Ambiguous stable note id(s) in canonical Markdown; registry refresh aborted: " + details
        )
    return stable_ids


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
            raise FileTrackingError(
                "Working tree hash must be exactly 64 lowercase hexadecimal characters."
            )

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


def list_registered_stable_identities(registry: Registry) -> tuple[RegisteredStableIdentity, ...]:
    """Return the current disposable stable-id mapping in deterministic order."""
    with registry.connect_read_only() as conn:
        rows = conn.execute(
            """
            SELECT stable_id, vault_path, content_hash
            FROM files
            WHERE stable_id IS NOT NULL AND is_deleted = 0
            ORDER BY stable_id, vault_path
            """
        ).fetchall()
    return tuple(
        RegisteredStableIdentity(
            stable_id=str(row["stable_id"]),
            path=str(row["vault_path"]),
            content_hash=str(row["content_hash"]) if row["content_hash"] is not None else None,
        )
        for row in rows
    )


def resolve_registered_stable_id(
    registry: Registry, stable_id: str
) -> RegisteredStableIdentity | None:
    """Resolve one active registry identity; the schema and scan preflight reject ambiguity."""
    if not stable_id.strip():
        raise FileTrackingError("Stable note id cannot be empty.")
    with registry.connect_read_only() as conn:
        rows = conn.execute(
            """
            SELECT stable_id, vault_path, content_hash
            FROM files
            WHERE stable_id = ? AND is_deleted = 0
            ORDER BY vault_path
            """,
            (stable_id,),
        ).fetchall()
    if len(rows) > 1:
        raise FileTrackingError(f"Stable note id {stable_id!r} is ambiguous in registry state.")
    if not rows:
        return None
    row = rows[0]
    return RegisteredStableIdentity(
        stable_id=str(row["stable_id"]),
        path=str(row["vault_path"]),
        content_hash=str(row["content_hash"]) if row["content_hash"] is not None else None,
    )


def register_scan(registry: Registry, vault_root: Path, entries: list[VaultFile]) -> ScanResult:
    """Hash and register scanned files into the registry database.

    Markdown frontmatter ``id`` is recorded as disposable identity metadata. When exactly one
    existing registry record has that stable id, a changed path is reconciled as a relocation
    while preserving the registry row identity. Duplicate stable ids abort the entire refresh
    before any registry write.
    """
    seen = set()
    for entry in entries:
        path_str = str(entry.path)
        if path_str in seen:
            raise FileTrackingError(f"Duplicate normalized path in scan entries: {path_str}")
        seen.add(path_str)

    stable_ids = _scan_stable_ids(vault_root, entries)
    new_paths: list[str] = []
    modified_paths: list[str] = []
    unchanged_paths: list[str] = []
    deleted_paths: list[str] = []
    renamed_paths: list[tuple[str, str]] = []

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
                stable_id = stable_ids[path_str]
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
                    """
                    SELECT id, stable_id, content_hash, is_deleted
                    FROM files WHERE vault_path = ?
                    """,
                    (path_str,),
                ).fetchone()
                identity_row = None
                if stable_id is not None:
                    identity_row = conn.execute(
                        """
                        SELECT id, vault_path, stable_id, content_hash, is_deleted
                        FROM files WHERE stable_id = ?
                        """,
                        (stable_id,),
                    ).fetchone()

                if (
                    stable_id is not None
                    and identity_row is not None
                    and identity_row["vault_path"] != path_str
                ):
                    old_path = str(identity_row["vault_path"])
                    if row is not None and row["id"] != identity_row["id"]:
                        raise FileTrackingError(
                            f"Cannot relocate stable note id {stable_id!r} to {path_str}: "
                            "the destination path already belongs to another registry record."
                        )
                    previous_hash = identity_row["content_hash"]
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
                            stable_id,
                            content_hash,
                            size_bytes,
                            mtime_ns,
                            identity_row["id"],
                        ),
                    )
                    renamed_paths.append((old_path, path_str))
                    if previous_hash != content_hash:
                        modified_paths.append(path_str)
                    continue

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
                            stable_id,
                            entry.file_type,
                            content_hash,
                            size_bytes,
                            mtime_ns,
                        ),
                    )
                    new_paths.append(path_str)
                else:
                    existing_stable_id = row["stable_id"]
                    if (
                        stable_id is not None
                        and existing_stable_id is not None
                        and existing_stable_id != stable_id
                    ):
                        raise FileTrackingError(
                            f"Stable note identity changed in place at {path_str}: "
                            f"{existing_stable_id!r} -> {stable_id!r}."
                        )
                    db_hash = row["content_hash"]
                    is_deleted = row["is_deleted"]
                    effective_stable_id = stable_id if stable_id is not None else existing_stable_id

                    if is_deleted == 1 or db_hash != content_hash:
                        conn.execute(
                            f"""
                            UPDATE files
                            SET stable_id = ?, content_hash = ?, size_bytes = ?, mtime_ns = ?,
                                last_seen_at = {now_expr}, is_deleted = 0
                            WHERE vault_path = ?
                            """,
                            (
                                effective_stable_id,
                                content_hash,
                                size_bytes,
                                mtime_ns,
                                path_str,
                            ),
                        )
                        modified_paths.append(path_str)
                    else:
                        conn.execute(
                            f"""
                            UPDATE files
                            SET stable_id = ?, last_seen_at = {now_expr}
                            WHERE vault_path = ?
                            """,
                            (effective_stable_id, path_str),
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
        renamed=sorted(renamed_paths),
    )
