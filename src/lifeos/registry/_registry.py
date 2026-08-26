"""SQLite registry initialization and migration execution."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lifeos.registry import _migrations


class RegistryError(RuntimeError):
    """Base class for registry-specific failures."""


class RegistryOpenError(RegistryError):
    """Raised when a registry database or its parent cannot be opened."""


class RegistryMigrationError(RegistryError):
    """Raised when a migration cannot be applied transactionally."""


class RegistryHistoryError(RegistryError):
    """Raised when recorded migration history is inconsistent."""


class UnsupportedSchemaVersionError(RegistryError):
    """Raised when a database was created by a newer LifeOS schema."""


class Registry:
    """A caller-located SQLite registry with explicit initialization."""

    def __init__(self, database_path: Path, *, directory_fd: int | None = None) -> None:
        if directory_fd is None:
            self._database_path = Path(database_path).resolve(strict=False)
        else:
            # Keep the configured lexical runtime address for exclusion/reporting while SQLite
            # opens through the pinned directory descriptor below.
            self._database_path = Path(os.path.abspath(database_path))
        self._directory_fd = directory_fd

    @property
    def database_path(self) -> Path:
        """Return the normalized logical database path without touching the filesystem."""
        return self._database_path

    def _validate_bound_directory(self) -> None:
        if self._directory_fd is None:
            return
        try:
            state = os.fstat(self._directory_fd)
        except OSError as exc:
            raise RegistryOpenError("Registry runtime directory descriptor is unavailable") from exc
        if not stat.S_ISDIR(state.st_mode):
            raise RegistryOpenError("Registry runtime authority is not a directory")

    def _validate_bound_database_entry(self, *, allow_missing: bool) -> bool:
        if self._directory_fd is None:
            return self._database_path.exists()
        self._validate_bound_directory()
        try:
            state = os.stat(
                self._database_path.name,
                dir_fd=self._directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if allow_missing:
                return False
            return False
        except OSError as exc:
            raise RegistryOpenError("Could not inspect registry database entry") from exc
        if not stat.S_ISREG(state.st_mode):
            raise RegistryOpenError("Registry database entry is not a regular file")
        return True

    def _sqlite_database_path(self, *, allow_missing: bool) -> Path:
        if self._directory_fd is None:
            return self._database_path
        self._validate_bound_database_entry(allow_missing=allow_missing)
        proc_directory = Path(f"/proc/self/fd/{self._directory_fd}")
        if not proc_directory.exists():
            raise RegistryOpenError(
                "Descriptor-bound registry access requires Linux /proc/self/fd support"
            )
        return proc_directory / self._database_path.name

    @property
    def schema_version(self) -> int:
        """Return the applied version, or zero when the database does not exist."""
        if not self._validate_bound_database_entry(allow_missing=True):
            return 0

        plan = _migration_plan()
        with self._connection(create=False, read_only=True) as connection:
            history = _read_migration_history(connection, plan)
            if history:
                _validate_schema_objects(
                    connection,
                    plan=plan,
                    applied_version=history[-1][0],
                )
            return history[-1][0] if history else 0

    def initialize(self) -> None:
        """Create the direct parent and database, then apply missing migrations."""
        self._ensure_parent_directory()
        plan = _migration_plan()

        with self._connection(create=True, read_only=False) as connection:
            while True:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                except sqlite3.Error as exc:
                    raise RegistryMigrationError(
                        f"Could not begin a migration transaction for {self._database_path}: {exc}"
                    ) from exc

                migration: _migrations.Migration | None = None
                try:
                    history = _read_migration_history(connection, plan)
                    if len(history) == len(plan):
                        connection.commit()
                        break

                    migration = plan[len(history)]
                    for statement in migration.statements:
                        connection.execute(statement)
                    connection.execute(
                        """
                        INSERT INTO schema_migrations (version, name, applied_at)
                        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        """,
                        (migration.version, migration.name),
                    )
                    connection.commit()
                except RegistryError as exc:
                    rollback_error = _rollback(connection)
                    if rollback_error is not None:
                        raise RegistryMigrationError(
                            "Registry validation failed and its transaction could not be "
                            f"rolled back: {rollback_error}"
                        ) from exc
                    raise
                except sqlite3.Error as exc:
                    rollback_error = _rollback(connection)
                    if migration is None:
                        detail = "while inspecting migration history"
                    else:
                        detail = f"in migration {migration.version} ({migration.name})"
                    rollback_detail = (
                        f" Rollback also failed: {rollback_error}"
                        if rollback_error is not None
                        else ""
                    )
                    raise RegistryMigrationError(
                        f"Registry migration failed {detail}; its transaction was rolled back: "
                        f"{exc}.{rollback_detail}"
                    ) from exc

            _validate_schema_objects(
                connection,
                plan=plan,
                applied_version=plan[-1].version,
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a foreign-key-enabled connection to an initialized database."""
        plan = _migration_plan()
        with self._connection(create=False, read_only=False) as connection:
            history = _read_migration_history(connection, plan)
            if len(history) != len(plan):
                applied_version = history[-1][0] if history else 0
                raise RegistryHistoryError(
                    f"Registry schema version {applied_version} is not initialized to current "
                    f"version {plan[-1].version}; call initialize() first."
                )
            _validate_schema_objects(
                connection,
                plan=plan,
                applied_version=history[-1][0],
            )
            yield connection

    @contextmanager
    def connect_read_only(self) -> Iterator[sqlite3.Connection]:
        """Yield a read-only connection to an initialized database."""
        plan = _migration_plan()
        with self._connection(create=False, read_only=True) as connection:
            history = _read_migration_history(connection, plan)
            if len(history) != len(plan):
                applied_version = history[-1][0] if history else 0
                raise RegistryHistoryError(
                    f"Registry schema version {applied_version} is not initialized to current "
                    f"version {plan[-1].version}; call initialize() first."
                )
            _validate_schema_objects(
                connection,
                plan=plan,
                applied_version=history[-1][0],
            )
            yield connection

    def _ensure_parent_directory(self) -> None:
        if self._directory_fd is not None:
            self._validate_bound_directory()
            return

        parent = self._database_path.parent
        if parent.exists():
            if not parent.is_dir():
                raise RegistryOpenError(f"Registry parent path is not a directory: {parent}")
            return

        try:
            parent.mkdir()
        except OSError as exc:
            raise RegistryOpenError(
                f"Could not create registry parent directory {parent}: {exc}"
            ) from exc

    @contextmanager
    def _connection(
        self,
        *,
        create: bool,
        read_only: bool,
    ) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection(create=create, read_only=read_only)
        try:
            yield connection
        finally:
            connection.close()

    def _open_connection(self, *, create: bool, read_only: bool) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            database_path = self._sqlite_database_path(allow_missing=create)
            if create:
                connection = sqlite3.connect(
                    database_path,
                    isolation_level=None,
                    timeout=5.0,
                )
            else:
                mode = "ro" if read_only else "rw"
                uri = f"{database_path.as_uri()}?mode={mode}"
                connection = sqlite3.connect(
                    uri,
                    uri=True,
                    isolation_level=None,
                    timeout=5.0,
                )

            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            row = connection.execute("PRAGMA foreign_keys").fetchone()
            if row is None or row[0] != 1:
                raise RegistryOpenError(
                    f"Could not enable foreign-key enforcement for {self._database_path}."
                )
            return connection
        except RegistryOpenError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise RegistryOpenError(
                f"Could not open registry database {self._database_path}: {exc}"
            ) from exc


def _migration_plan() -> tuple[_migrations.Migration, ...]:
    plan = tuple(sorted(_migrations.MIGRATIONS, key=lambda migration: migration.version))
    versions = [migration.version for migration in plan]
    names = [migration.name for migration in plan]

    if not plan:
        raise RegistryMigrationError("The registry has no declared migrations.")
    if any(version <= 0 for version in versions) or len(versions) != len(set(versions)):
        raise RegistryMigrationError("Registry migration versions must be unique and positive.")
    if any(not name.strip() for name in names) or len(names) != len(set(names)):
        raise RegistryMigrationError("Registry migration names must be unique and non-empty.")
    if any(not migration.statements for migration in plan):
        raise RegistryMigrationError("Every registry migration must contain SQL statements.")
    return plan


def _read_migration_history(
    connection: sqlite3.Connection,
    plan: tuple[_migrations.Migration, ...],
) -> list[tuple[int, str, str]]:
    try:
        object_rows = connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        objects = {(str(row[0]), str(row[1])) for row in object_rows}
        tables = {name for object_type, name in objects if object_type == "table"}

        if "schema_migrations" not in tables:
            if objects:
                names = ", ".join(f"{object_type} {name}" for object_type, name in sorted(objects))
                raise RegistryHistoryError(
                    "Registry database contains schema objects without migration history: " + names
                )
            return []

        rows = connection.execute(
            """
            SELECT version, name, applied_at
            FROM schema_migrations
            ORDER BY version
            """
        ).fetchall()
    except RegistryHistoryError:
        raise
    except sqlite3.Error as exc:
        raise RegistryHistoryError(f"Could not inspect registry migration history: {exc}") from exc

    if not rows:
        raise RegistryHistoryError(
            "Registry migration history table exists but contains no applied migrations."
        )

    history: list[tuple[int, str, str]] = []
    for row in rows:
        version, name, applied_at = row
        if (
            not isinstance(version, int)
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(applied_at, str)
            or not applied_at.strip()
        ):
            raise RegistryHistoryError("Registry migration history contains invalid values.")
        history.append((version, name, applied_at))

    latest_supported = plan[-1].version
    future_versions = [version for version, _, _ in history if version > latest_supported]
    if future_versions:
        raise UnsupportedSchemaVersionError(
            f"Registry schema version {max(future_versions)} is newer than supported "
            f"version {latest_supported}."
        )

    if len(history) > len(plan):
        raise RegistryHistoryError("Registry migration history has more entries than expected.")

    for position, (version, name, _) in enumerate(history):
        expected = plan[position]
        if version != expected.version or name != expected.name:
            raise RegistryHistoryError(
                "Registry migration history is inconsistent at position "
                f"{position + 1}: found {version} ({name}), expected "
                f"{expected.version} ({expected.name})."
            )
    return history


def _validate_schema_objects(
    connection: sqlite3.Connection,
    *,
    plan: tuple[_migrations.Migration, ...],
    applied_version: int,
) -> None:
    try:
        rows = connection.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE type IN ('table', 'index')
            """
        ).fetchall()
    except sqlite3.Error as exc:
        raise RegistryHistoryError(f"Could not inspect registry schema objects: {exc}") from exc

    tables = {str(row[1]) for row in rows if row[0] == "table"}
    indexes = {str(row[1]) for row in rows if row[0] == "index"}
    required_tables: set[str] = set()
    required_indexes: set[str] = set()
    for migration in plan:
        if migration.version > applied_version:
            break
        required_tables.update(migration.required_tables)
        required_indexes.update(migration.required_indexes)

    missing_tables = required_tables - tables
    missing_indexes = required_indexes - indexes
    if missing_tables or missing_indexes:
        details: list[str] = []
        if missing_tables:
            details.append("missing tables: " + ", ".join(sorted(missing_tables)))
        if missing_indexes:
            details.append("missing indexes: " + ", ".join(sorted(missing_indexes)))
        raise RegistryHistoryError(
            "Registry schema does not match its migration history (" + "; ".join(details) + ")."
        )


def _rollback(connection: sqlite3.Connection) -> sqlite3.Error | None:
    if not connection.in_transaction:
        return None
    try:
        connection.rollback()
    except sqlite3.Error as exc:
        return exc
    return None
