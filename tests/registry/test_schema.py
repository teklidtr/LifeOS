from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
import pytest

from lifeos.registry import (
    CURRENT_SCHEMA_VERSION,
    Registry,
    RegistryHistoryError,
    RegistryMigrationError,
    RegistryOpenError,
    UnsupportedSchemaVersionError,
)
from lifeos.registry import _migrations

EXPECTED_COLUMNS = {
    "schema_migrations": {"version", "name", "applied_at"},
    "files": {
        "id",
        "vault_path",
        "stable_id",
        "file_kind",
        "content_hash",
        "size_bytes",
        "mtime_ns",
        "first_seen_at",
        "last_seen_at",
        "is_deleted",
    },
    "source_versions": {
        "id",
        "source_id",
        "version_hash",
        "original_file_id",
        "observed_at",
        "sanitization_metadata",
    },
    "provenance_documents": {
        "derived_path",
        "schema_version",
        "generator_id",
        "generator_version",
        "prompt_schema_version",
        "model_id",
        "created_at",
    },
    "provenance_sources": {
        "derived_path",
        "source_index",
        "source_path",
        "source_hash",
    },
    "generated_outputs": {
        "id",
        "output_id",
        "target_path",
        "generator_id",
        "generator_version",
        "output_hash",
        "created_at",
        "updated_at",
    },
    "proposals": {
        "id",
        "status",
        "title",
        "created_at",
        "updated_at",
    },
}


def _initialized_registry(tmp_path: Path, name: str = ".lifeos") -> Registry:
    registry = Registry(tmp_path / name / "state.sqlite")
    registry.initialize()
    return registry


def _insert_file(
    connection: sqlite3.Connection,
    *,
    vault_path: str = "notes/example.md",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO files (vault_path, file_kind, content_hash, size_bytes, mtime_ns)
        VALUES (?, ?, ?, ?, ?)
        """,
        (vault_path, "markdown", "sha256:example", 42, 123456789),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _unique_indexes(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    columns: set[tuple[str, ...]] = set()
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        if row[2] != 1:
            continue
        index_name = str(row[1]).replace('"', '""')
        index_columns = tuple(
            str(index_row[2])
            for index_row in connection.execute(f'PRAGMA index_info("{index_name}")')
        )
        columns.add(index_columns)
    return columns


def test_fresh_database_initializes_current_schema(tmp_path: Path) -> None:
    runtime_dir = tmp_path / ".lifeos"
    database_path = runtime_dir / "state.sqlite"
    registry = Registry(database_path)

    assert not runtime_dir.exists()
    registry.initialize()

    assert registry.database_path == database_path.resolve()
    assert database_path.is_file()
    assert set(runtime_dir.iterdir()) == {database_path}
    assert registry.schema_version == CURRENT_SCHEMA_VERSION == 4


def test_all_required_tables_exist(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert tables == set(EXPECTED_COLUMNS)


def test_required_columns_indexes_and_foreign_key_exist(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        for table, expected in EXPECTED_COLUMNS.items():
            table_info = {
                str(row[1]): row for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            assert set(table_info) == expected

            for row in table_info.values():
                assert row[2] in {"INTEGER", "TEXT"}

        migrations_info = {
            str(row[1]): row for row in connection.execute('PRAGMA table_info("schema_migrations")')
        }
        assert migrations_info["version"][2] == "INTEGER"
        assert migrations_info["version"][5] == 1
        assert migrations_info["name"][2] == "TEXT"
        assert migrations_info["name"][3] == 1
        assert migrations_info["applied_at"][3] == 1

        files_info = {str(row[1]): row for row in connection.execute('PRAGMA table_info("files")')}
        assert files_info["vault_path"][3] == 1
        assert files_info["file_kind"][3] == 1
        assert files_info["stable_id"][3] == 0
        assert files_info["content_hash"][3] == 0
        assert files_info["size_bytes"][3] == 0
        assert files_info["mtime_ns"][3] == 0
        assert files_info["is_deleted"][3] == 1
        assert files_info["is_deleted"][4] == "0"
        assert "strftime" in str(files_info["first_seen_at"][4])
        assert "strftime" in str(files_info["last_seen_at"][4])

        source_info = {
            str(row[1]): row for row in connection.execute('PRAGMA table_info("source_versions")')
        }
        assert source_info["source_id"][3] == 1
        assert source_info["version_hash"][3] == 1
        assert source_info["original_file_id"][3] == 1
        assert source_info["sanitization_metadata"][3] == 0

        output_info = {
            str(row[1]): row for row in connection.execute('PRAGMA table_info("generated_outputs")')
        }
        for column in (
            "output_id",
            "target_path",
            "generator_id",
            "generator_version",
            "output_hash",
            "created_at",
            "updated_at",
        ):
            assert output_info[column][3] == 1

        proposals_info = {
            str(row[1]): row for row in connection.execute('PRAGMA table_info("proposals")')
        }
        for column in ("id", "status", "title", "created_at", "updated_at"):
            assert proposals_info[column][3] == 1

        assert {("name",)} <= _unique_indexes(connection, "schema_migrations")
        assert {("vault_path",)} <= _unique_indexes(connection, "files")
        assert ("stable_id",) not in _unique_indexes(connection, "files")
        assert {("source_id", "version_hash")} <= _unique_indexes(connection, "source_versions")
        assert {("output_id",), ("target_path",)} <= _unique_indexes(
            connection, "generated_outputs"
        )
        assert {("id",)} <= _unique_indexes(connection, "proposals")

        stable_id_indexes = {
            str(row[1]): int(row[2])
            for row in connection.execute('PRAGMA index_list("files")')
            if str(row[1]) == "idx_files_stable_id"
        }
        assert stable_id_indexes == {"idx_files_stable_id": 0}

        explicit_indexes = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'
                """
            )
        }
        assert explicit_indexes == _migrations.REQUIRED_INDEXES

        foreign_keys = connection.execute('PRAGMA foreign_key_list("source_versions")').fetchall()
        assert len(foreign_keys) == 1
        assert foreign_keys[0][2] == "files"
        assert foreign_keys[0][3] == "original_file_id"
        assert foreign_keys[0][4] == "id"
        assert foreign_keys[0][6] == "RESTRICT"


def test_database_constraints_reject_invalid_identity_and_paths(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        file_id = _insert_file(connection)

        with pytest.raises(sqlite3.IntegrityError):
            _insert_file(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_file(connection, vault_path="/absolute/path.md")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO files (vault_path, file_kind, size_bytes) VALUES (?, ?, ?)",
                ("notes/negative.md", "markdown", -1),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO files (vault_path, file_kind, size_bytes) VALUES (?, ?, ?)",
                ("notes/text-size.md", "markdown", "not-a-number"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO files (vault_path, file_kind, mtime_ns) VALUES (?, ?, ?)",
                ("notes/text-mtime.md", "markdown", "not-a-number"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO files (vault_path, file_kind, is_deleted) VALUES (?, ?, ?)",
                ("notes/deletion-state.md", "markdown", 2),
            )

        connection.execute(
            """
            INSERT INTO source_versions (source_id, version_hash, original_file_id)
            VALUES (?, ?, ?)
            """,
            ("source-1", "sha256:v1", file_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_versions (source_id, version_hash, original_file_id)
                VALUES (?, ?, ?)
                """,
                ("source-1", "sha256:v1", file_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM files WHERE id = ?", (file_id,))

        connection.execute(
            """
            INSERT INTO generated_outputs
                (output_id, target_path, generator_id, generator_version, output_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("output-1", "indexes/wiki.md", "wiki-index", "1", "sha256:out"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO generated_outputs
                    (output_id, target_path, generator_id, generator_version, output_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("output-2", "indexes/wiki.md", "wiki-index", "1", "sha256:out2"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO generated_outputs
                    (output_id, target_path, generator_id, generator_version, output_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("output-1", "indexes/other.md", "wiki-index", "1", "sha256:out2"),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO generated_outputs
                    (output_id, target_path, generator_id, generator_version, output_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("output-3", "/absolute.md", "wiki-index", "1", "sha256:out3"),
            )


def test_schema_version_and_migration_metadata_are_recorded(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        rows = connection.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [(row[0], row[1]) for row in rows] == [
        (1, "initial_registry_schema"),
        (2, "proposals_schema"),
        (3, "provenance_schema"),
        (4, "scoped_stable_identity_schema"),
    ]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", rows[0][2])


def test_repeated_initialization_is_idempotent_and_preserves_rows(tmp_path: Path) -> None:
    database_path = tmp_path / ".lifeos" / "state.sqlite"
    registry = Registry(database_path)
    registry.initialize()

    with registry.connect() as connection:
        file_id = _insert_file(connection)
        before_file = tuple(
            connection.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        )
        before_history = [
            tuple(row)
            for row in connection.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            )
        ]

    registry.initialize()
    Registry(database_path).initialize()

    with registry.connect() as connection:
        after_file = tuple(
            connection.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        )
        after_history = [
            tuple(row)
            for row in connection.execute(
                "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
            )
        ]

    assert after_file == before_file
    assert after_history == before_history
    assert registry.schema_version == CURRENT_SCHEMA_VERSION


def test_foreign_keys_are_enabled_and_enforced(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO source_versions (source_id, version_hash, original_file_id)
                VALUES (?, ?, ?)
                """,
                ("source-missing", "sha256:missing", 999),
            )


def test_migrations_are_applied_in_version_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    migration_three = _migrations.Migration(
        998,
        "create_order_probe",
        (
            "CREATE TABLE migration_order (position INTEGER NOT NULL)",
            "INSERT INTO migration_order (position) VALUES (998)",
        ),
    )
    migration_four = _migrations.Migration(
        999,
        "extend_order_probe",
        ("INSERT INTO migration_order (position) VALUES (999)",),
    )
    monkeypatch.setattr(
        _migrations,
        "MIGRATIONS",
        (migration_four, *_migrations.MIGRATIONS, migration_three),
    )
    registry = Registry(tmp_path / ".lifeos" / "state.sqlite")

    registry.initialize()

    with registry.connect() as connection:
        positions = [
            row[0]
            for row in connection.execute("SELECT position FROM migration_order ORDER BY rowid")
        ]
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    assert positions == [998, 999]
    assert versions == [1, 2, 3, 4, 998, 999]


def test_failed_migration_rolls_back_without_partial_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _initialized_registry(tmp_path)
    failing_migration = _migrations.Migration(
        998,
        "failing_test_migration",
        (
            "CREATE TABLE rollback_probe (id INTEGER PRIMARY KEY)",
            "THIS IS NOT VALID SQL",
        ),
    )
    monkeypatch.setattr(
        _migrations,
        "MIGRATIONS",
        (*_migrations.MIGRATIONS, failing_migration),
    )

    with pytest.raises(RegistryMigrationError, match="transaction was rolled back") as exc_info:
        registry.initialize()

    assert isinstance(exc_info.value.__cause__, sqlite3.Error)
    with closing(sqlite3.connect(registry.database_path)) as connection:
        probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'rollback_probe'"
        ).fetchone()
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    assert probe is None
    assert versions == [1, 2, 3, 4]
    assert registry.schema_version == 4


def test_unsupported_future_schema_version_fails_without_changes(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)
    with registry.connect() as connection:
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (CURRENT_SCHEMA_VERSION + 1, "future_migration"),
        )

    with pytest.raises(UnsupportedSchemaVersionError, match="newer than supported"):
        registry.initialize()

    with closing(sqlite3.connect(registry.database_path)) as connection:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    assert versions == [1, 2, 3, 4, 5]


def test_inconsistent_migration_history_fails_clearly(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)
    with registry.connect() as connection:
        connection.execute(
            "UPDATE schema_migrations SET name = ? WHERE version = ?",
            ("tampered_name", 1),
        )

    with pytest.raises(RegistryHistoryError, match="inconsistent"):
        registry.initialize()


def test_schema_inspection_is_version_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _initialized_registry(tmp_path)
    future_migration = _migrations.Migration(
        998,
        "future_table",
        ("CREATE TABLE future_table (id INTEGER PRIMARY KEY)",),
        required_tables=frozenset({"future_table"}),
    )
    monkeypatch.setattr(
        _migrations,
        "MIGRATIONS",
        (*_migrations.MIGRATIONS, future_migration),
    )

    assert registry.schema_version == 4
    with pytest.raises(RegistryHistoryError, match="call initialize"):
        with registry.connect():
            pass


def test_import_construction_and_inspection_do_not_create_files(tmp_path: Path) -> None:
    import_directory = tmp_path / "import-check"
    import_directory.mkdir()
    subprocess.run(
        [sys.executable, "-c", "import lifeos.registry"],
        cwd=import_directory,
        check=True,
        capture_output=True,
        text=True,
    )
    assert not any(import_directory.iterdir())

    database_path = tmp_path / "missing-runtime" / "state.sqlite"
    registry = Registry(database_path)
    assert registry.schema_version == 0
    with pytest.raises(RegistryOpenError, match="Could not open registry database"):
        with registry.connect():
            pass
    assert not database_path.parent.exists()

    empty_database = tmp_path / "empty.sqlite"
    empty_database.touch()
    with pytest.raises(RegistryHistoryError, match="call initialize"):
        with Registry(empty_database).connect():
            pass


def test_separate_databases_do_not_share_state(tmp_path: Path) -> None:
    first = _initialized_registry(tmp_path, "first")
    second = _initialized_registry(tmp_path, "second")

    with first.connect() as connection:
        _insert_file(connection, vault_path="only-in-first.md")

    with first.connect() as connection:
        first_count = connection.execute("SELECT count(*) FROM files").fetchone()[0]
    with second.connect() as connection:
        second_count = connection.execute("SELECT count(*) FROM files").fetchone()[0]

    assert first_count == 1
    assert second_count == 0
    assert first.schema_version == second.schema_version == CURRENT_SCHEMA_VERSION


@pytest.mark.parametrize("failure_kind", ["parent-is-file", "database-is-directory"])
def test_database_open_failures_are_wrapped_clearly(tmp_path: Path, failure_kind: str) -> None:
    if failure_kind == "parent-is-file":
        parent = tmp_path / "runtime-file"
        parent.write_text("not a directory", encoding="utf-8")
        database_path = parent / "state.sqlite"
    else:
        database_path = tmp_path / "database-directory"
        database_path.mkdir()

    with pytest.raises(RegistryOpenError):
        Registry(database_path).initialize()


def test_version_1_upgrades_to_current_schema_correctly(tmp_path: Path) -> None:
    database_path = tmp_path / "upgrade_test.sqlite"

    # Construct a genuine version 1 database using the first migration.
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        for stmt in _migrations.MIGRATIONS[0].statements:
            connection.execute(stmt)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (_migrations.MIGRATIONS[0].version, _migrations.MIGRATIONS[0].name),
        )
        file_id = _insert_file(connection, vault_path="notes/v1_file.md")
        connection.execute(
            """
            INSERT INTO source_versions (source_id, version_hash, original_file_id)
            VALUES (?, ?, ?)
            """,
            ("source-v1", "sha256:v1", file_id),
        )
        connection.execute("COMMIT")

    registry = Registry(database_path)
    # Ensure proposals doesn't exist yet.
    with closing(sqlite3.connect(database_path)) as connection:
        probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'proposals'"
        ).fetchone()
        assert probe is None

    # Run initialization to trigger every migration through v4.
    registry.initialize()

    with registry.connect() as connection:
        assert registry.schema_version == CURRENT_SCHEMA_VERSION == 4

        probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'proposals'"
        ).fetchone()
        assert probe is not None

        idx_probe = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'proposals_status_idx'"
        ).fetchone()
        assert idx_probe is not None

        # Verify v1 file identity and source-version lineage survive the v4 table rebuild.
        row = connection.execute("SELECT vault_path FROM files WHERE id = ?", (file_id,)).fetchone()
        assert row["vault_path"] == "notes/v1_file.md"
        source_row = connection.execute(
            "SELECT original_file_id FROM source_versions WHERE source_id = ?",
            ("source-v1",),
        ).fetchone()
        assert source_row is not None
        assert source_row["original_file_id"] == file_id
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM files WHERE id = ?", (file_id,))

    # Idempotent.
    Registry(database_path).initialize()


def test_proposals_table_constraints(tmp_path: Path) -> None:
    registry = _initialized_registry(tmp_path)

    with registry.connect() as connection:
        # Valid insert
        connection.execute(
            """
            INSERT INTO proposals (id, status, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("prop-123", "draft", "A Title", "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"),
        )

        # Read back unchanged
        row = connection.execute("SELECT * FROM proposals WHERE id = ?", ("prop-123",)).fetchone()
        assert row["id"] == "prop-123"
        assert row["title"] == "A Title"

        # Duplicate ID rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (id, status, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("prop-123", "pending", "Another", "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"),
            )

        # Null ID rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (status, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("pending", "Title", "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"),
            )

        # Null status rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("prop-124", "Title", "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"),
            )

        # Null title rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("prop-125", "draft", "2026-07-13T00:00:00Z", "2026-07-13T01:00:00Z"),
            )

        # Null created_at rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (id, status, title, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                ("prop-126", "draft", "Title", "2026-07-13T01:00:00Z"),
            )

        # Null updated_at rejected
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO proposals (id, status, title, created_at)
                VALUES (?, ?, ?, ?)
                """,
                ("prop-127", "draft", "Title", "2026-07-13T00:00:00Z"),
            )
