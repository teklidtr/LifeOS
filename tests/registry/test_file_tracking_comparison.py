"""Tests for read-only registry file comparison."""

import hashlib
from pathlib import Path

import pytest

from lifeos.registry import Registry, RegistryOpenError, UnsupportedSchemaVersionError
from lifeos.registry.file_tracking import (
    FileRegistrationState,
    FileTrackingError,
    compare_registered_file,
    hash_file_content,
    register_scan,
)
from lifeos.scanner import VaultFile


def test_hash_file_content_matches_registration() -> None:
    """Canonical bytes hash must match the existing registration hash logic."""
    content = b"hello world\n"
    expected = hashlib.sha256(content).hexdigest()
    assert hash_file_content(content) == expected


def test_compare_registered_unchanged(tmp_path: Path) -> None:
    """A file in the registry with a matching hash is UNCHANGED."""
    vault = tmp_path / "vault"
    vault.mkdir()
    file_path = vault / "test.md"
    file_path.write_bytes(b"content")

    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    register_scan(registry, vault, [VaultFile(Path("test.md"), "markdown", len(b"content"))])

    result = compare_registered_file(
        registry,
        "test.md",
        hash_file_content(b"content")
    )
    assert result.state == FileRegistrationState.REGISTERED_UNCHANGED
    assert result.path == "test.md"
    assert result.working_tree_hash == hash_file_content(b"content")
    assert result.registry_hash == hash_file_content(b"content")


def test_compare_registered_modified(tmp_path: Path) -> None:
    """A file in the registry with a mismatched hash is MODIFIED."""
    vault = tmp_path / "vault"
    vault.mkdir()
    file_path = vault / "test.md"
    file_path.write_bytes(b"content")

    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    register_scan(registry, vault, [VaultFile(Path("test.md"), "markdown", len(b"content"))])

    new_hash = hash_file_content(b"new content")
    result = compare_registered_file(
        registry,
        "test.md",
        new_hash
    )
    assert result.state == FileRegistrationState.REGISTERED_MODIFIED
    assert result.registry_hash == hash_file_content(b"content")
    assert result.working_tree_hash == new_hash


def test_compare_registered_missing(tmp_path: Path) -> None:
    """A file in the registry but missing from disk is REGISTERED_MISSING."""
    vault = tmp_path / "vault"
    vault.mkdir()
    file_path = vault / "test.md"
    file_path.write_bytes(b"content")

    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    register_scan(registry, vault, [VaultFile(Path("test.md"), "markdown", len(b"content"))])

    result = compare_registered_file(
        registry,
        "test.md",
        None
    )
    assert result.state == FileRegistrationState.REGISTERED_MISSING
    assert result.registry_hash == hash_file_content(b"content")
    assert result.working_tree_hash is None


def test_compare_unregistered_present(tmp_path: Path) -> None:
    """A file absent from the registry but present on disk is UNREGISTERED_PRESENT."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    content_hash = hash_file_content(b"content")
    result = compare_registered_file(
        registry,
        "test.md",
        content_hash
    )
    assert result.state == FileRegistrationState.UNREGISTERED_PRESENT
    assert result.registry_hash is None
    assert result.working_tree_hash == content_hash


def test_compare_unregistered_missing(tmp_path: Path) -> None:
    """A file absent from the registry and missing from disk is UNREGISTERED_MISSING."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    result = compare_registered_file(
        registry,
        "test.md",
        None
    )
    assert result.state == FileRegistrationState.UNREGISTERED_MISSING
    assert result.registry_hash is None
    assert result.working_tree_hash is None


def test_compare_tombstoned_file_is_unregistered(tmp_path: Path) -> None:
    """A file marked as is_deleted in the registry behaves as unregistered."""
    vault = tmp_path / "vault"
    vault.mkdir()
    file_path = vault / "test.md"
    file_path.write_bytes(b"content")

    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    register_scan(registry, vault, [VaultFile(Path("test.md"), "markdown", len(b"content"))])

    # Delete from scan to mark as deleted
    register_scan(registry, vault, [])

    # Present on disk, but tombstoned
    working_hash = hash_file_content(b"content")
    result1 = compare_registered_file(registry, "test.md", working_hash)
    assert result1.state == FileRegistrationState.UNREGISTERED_PRESENT
    assert result1.registry_hash is None

    # Missing from disk, and tombstoned
    result2 = compare_registered_file(registry, "test.md", None)
    assert result2.state == FileRegistrationState.UNREGISTERED_MISSING
    assert result2.registry_hash is None


def test_path_validation_rejects_invalid_paths(tmp_path: Path) -> None:
    """Comparison rejects malformed paths before doing work."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    # Does not even need to be initialized since path validation happens first

    with pytest.raises(FileTrackingError, match="Vault path cannot be empty"):
        compare_registered_file(registry, "", None)

    with pytest.raises(FileTrackingError, match="Vault path cannot be absolute"):
        compare_registered_file(registry, "/abs/path", None)

    with pytest.raises(FileTrackingError, match="Vault path cannot contain dot components"):
        compare_registered_file(registry, "dir/../file.md", None)

    with pytest.raises(FileTrackingError, match="Vault path is not normalized"):
        compare_registered_file(registry, "./file.md", None)

    with pytest.raises(FileTrackingError, match="Vault path cannot contain backslashes"):
        compare_registered_file(registry, "dir\\file.md", None)

    with pytest.raises(FileTrackingError, match="Vault path cannot contain NUL"):
        compare_registered_file(registry, "dir\0file", None)

    with pytest.raises(FileTrackingError, match="Vault path is not normalized"):
        compare_registered_file(registry, "dir//file.md", None)


def test_hash_validation_rejects_invalid_hashes(tmp_path: Path) -> None:
    """Comparison rejects malformed hashes."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)

    with pytest.raises(FileTrackingError, match="must be exactly 64 lowercase hexadecimal characters"):
        compare_registered_file(registry, "test.md", "short")

    with pytest.raises(FileTrackingError, match="must be exactly 64 lowercase hexadecimal characters"):
        compare_registered_file(registry, "test.md", "A" * 64)


def test_missing_database_raises_exception(tmp_path: Path) -> None:
    """A missing database remains absent and raises RegistryOpenError."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)

    with pytest.raises(RegistryOpenError):
        compare_registered_file(registry, "test.md", None)

    assert not db_path.exists()


def test_unsupported_old_schema_raises_exception(tmp_path: Path) -> None:
    """Old or unavailable registry is not migrated and raises."""
    db_path = tmp_path / "registry.db"
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE schema_migrations (version INTEGER, name TEXT, applied_at TEXT)")
        # Insert a very old version, skipping intermediate migrations so it fails history check
        conn.execute("INSERT INTO schema_migrations VALUES (1, 'very_old', '2026')")

    registry = Registry(db_path)

    with pytest.raises(Exception):
        compare_registered_file(registry, "test.md", None)


def test_unsupported_new_schema_raises_exception(tmp_path: Path) -> None:
    """A database with a future schema version raises UnsupportedSchemaVersionError."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO schema_migrations VALUES (9999, 'future', '2026')")

    with pytest.raises(UnsupportedSchemaVersionError):
        compare_registered_file(registry, "test.md", None)


def test_comparison_performs_no_writes(tmp_path: Path) -> None:
    """Comparison executes strictly in read-only mode, avoiding canonical-file and registry writes."""
    vault = tmp_path / "vault"
    vault.mkdir()
    file_path = vault / "test.md"
    file_path.write_bytes(b"content")

    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    register_scan(registry, vault, [VaultFile(Path("test.md"), "markdown", len(b"content"))])

    stat_before = db_path.stat()
    mtime_before = stat_before.st_mtime_ns

    # Read-only operation
    result = compare_registered_file(registry, "test.md", hash_file_content(b"new content"))

    assert result.state == FileRegistrationState.REGISTERED_MODIFIED

    stat_after = db_path.stat()
    assert stat_after.st_mtime_ns == mtime_before

    # Verify rows haven't changed using a direct connection
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT content_hash FROM files WHERE vault_path = 'test.md'").fetchone()
        assert row["content_hash"] == hash_file_content(b"content")


def test_repeated_comparison_is_deterministic(tmp_path: Path) -> None:
    """Multiple comparisons on the same registry state yield identical results."""
    db_path = tmp_path / "registry.db"
    registry = Registry(db_path)
    registry.initialize()

    working_hash = hash_file_content(b"content")

    result1 = compare_registered_file(registry, "test.md", working_hash)
    result2 = compare_registered_file(registry, "test.md", working_hash)

    assert result1 == result2
    assert result1.state == FileRegistrationState.UNREGISTERED_PRESENT
