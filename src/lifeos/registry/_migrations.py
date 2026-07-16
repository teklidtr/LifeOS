"""Transparent SQL migration definitions for the LifeOS registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    """One immutable, transactionally applied registry migration."""

    version: int
    name: str
    statements: tuple[str, ...]
    required_tables: frozenset[str] = frozenset()
    required_indexes: frozenset[str] = frozenset()


_INITIAL_TABLES = frozenset({"schema_migrations", "files", "source_versions", "generated_outputs"})
_INITIAL_INDEXES = frozenset(
    {
        "idx_files_content_hash",
        "idx_source_versions_original_file_id",
        "idx_generated_outputs_generator",
    }
)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="initial_registry_schema",
        statements=(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                name TEXT NOT NULL UNIQUE CHECK (trim(name) <> ''),
                applied_at TEXT NOT NULL CHECK (trim(applied_at) <> '')
            )
            """,
            """
            CREATE TABLE files (
                id INTEGER PRIMARY KEY,
                vault_path TEXT NOT NULL UNIQUE,
                stable_id TEXT UNIQUE,
                file_kind TEXT NOT NULL,
                content_hash TEXT,
                size_bytes INTEGER,
                mtime_ns INTEGER,
                first_seen_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                last_seen_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                is_deleted INTEGER NOT NULL DEFAULT 0,
                CHECK (
                    trim(vault_path) <> ''
                    AND substr(vault_path, 1, 1) <> '/'
                    AND substr(vault_path, -1, 1) <> '/'
                    AND instr(vault_path, char(92)) = 0
                    AND vault_path NOT GLOB '[A-Za-z]:/*'
                    AND vault_path NOT IN ('.', '..')
                    AND vault_path NOT LIKE './%'
                    AND vault_path NOT LIKE '../%'
                    AND vault_path NOT LIKE '%/./%'
                    AND vault_path NOT LIKE '%/../%'
                    AND vault_path NOT LIKE '%/.'
                    AND vault_path NOT LIKE '%/..'
                    AND vault_path NOT LIKE '%//%'
                ),
                CHECK (stable_id IS NULL OR trim(stable_id) <> ''),
                CHECK (trim(file_kind) <> ''),
                CHECK (content_hash IS NULL OR trim(content_hash) <> ''),
                CHECK (
                    size_bytes IS NULL
                    OR (typeof(size_bytes) = 'integer' AND size_bytes >= 0)
                ),
                CHECK (
                    mtime_ns IS NULL
                    OR (typeof(mtime_ns) = 'integer' AND mtime_ns >= 0)
                ),
                CHECK (is_deleted IN (0, 1)),
                CHECK (last_seen_at >= first_seen_at)
            )
            """,
            """
            CREATE TABLE source_versions (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                version_hash TEXT NOT NULL,
                original_file_id INTEGER NOT NULL,
                observed_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                sanitization_metadata TEXT,
                UNIQUE (source_id, version_hash),
                CHECK (trim(source_id) <> ''),
                CHECK (trim(version_hash) <> ''),
                FOREIGN KEY (original_file_id) REFERENCES files(id)
                    ON UPDATE RESTRICT ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE generated_outputs (
                id INTEGER PRIMARY KEY,
                output_id TEXT NOT NULL UNIQUE,
                target_path TEXT NOT NULL UNIQUE,
                generator_id TEXT NOT NULL,
                generator_version TEXT NOT NULL,
                output_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL
                    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                CHECK (trim(output_id) <> ''),
                CHECK (
                    trim(target_path) <> ''
                    AND substr(target_path, 1, 1) <> '/'
                    AND substr(target_path, -1, 1) <> '/'
                    AND instr(target_path, char(92)) = 0
                    AND target_path NOT GLOB '[A-Za-z]:/*'
                    AND target_path NOT IN ('.', '..')
                    AND target_path NOT LIKE './%'
                    AND target_path NOT LIKE '../%'
                    AND target_path NOT LIKE '%/./%'
                    AND target_path NOT LIKE '%/../%'
                    AND target_path NOT LIKE '%/.'
                    AND target_path NOT LIKE '%/..'
                    AND target_path NOT LIKE '%//%'
                ),
                CHECK (trim(generator_id) <> ''),
                CHECK (trim(generator_version) <> ''),
                CHECK (trim(output_hash) <> ''),
                CHECK (updated_at >= created_at)
            )
            """,
            """
            CREATE INDEX idx_files_content_hash
                ON files(content_hash)
                WHERE content_hash IS NOT NULL
            """,
            """
            CREATE INDEX idx_source_versions_original_file_id
                ON source_versions(original_file_id)
            """,
            """
            CREATE INDEX idx_generated_outputs_generator
                ON generated_outputs(generator_id, generator_version)
            """,
        ),
        required_tables=_INITIAL_TABLES,
        required_indexes=_INITIAL_INDEXES,
    ),
    Migration(
        version=2,
        name="proposals_schema",
        statements=(
            """
            CREATE TABLE proposals (
                id TEXT PRIMARY KEY NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX proposals_status_idx ON proposals(status)
            """,
        ),
        required_tables=frozenset({"proposals"}),
        required_indexes=frozenset({"proposals_status_idx"}),
    ),
    Migration(
        version=3,
        name="provenance_schema",
        statements=(
            """
            CREATE TABLE provenance_documents (
                derived_path TEXT PRIMARY KEY NOT NULL,
                schema_version INTEGER NOT NULL,
                generator_id TEXT NOT NULL,
                generator_version TEXT NOT NULL,
                prompt_schema_version TEXT NOT NULL,
                model_id TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE provenance_sources (
                derived_path TEXT NOT NULL,
                source_index INTEGER NOT NULL,
                source_path TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                PRIMARY KEY (derived_path, source_index),
                FOREIGN KEY (derived_path)
                    REFERENCES provenance_documents(derived_path)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX provenance_sources_source_path_idx
                ON provenance_sources(source_path)
            """,
        ),
        required_tables=frozenset({"provenance_documents", "provenance_sources"}),
        required_indexes=frozenset({"provenance_sources_source_path_idx"}),
    ),
)

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version

REQUIRED_TABLES = frozenset(
    table for migration in MIGRATIONS for table in migration.required_tables
)
REQUIRED_INDEXES = frozenset(
    index for migration in MIGRATIONS for index in migration.required_indexes
)
