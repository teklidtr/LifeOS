# Registry

The LifeOS registry stores deterministic operational facts. It does not replace
the Markdown vault and does not store full note or attachment contents, agent
interpretations, semantic embeddings, proposals, tasks, or Graphify state.

## Location and initialization

Callers choose the database path explicitly. The conventional location is:

```python
registry = Registry(config.runtime_dir / "state.sqlite")
```

Importing `lifeos.registry`, constructing `Registry`, reading migration metadata,
and loading configuration do not create files. `Registry.initialize()` is the
only initialization operation: it may create the database's direct parent and
the SQLite file, then applies missing migrations. It creates no other runtime
subdirectories and is not invoked automatically by the CLI or configuration
loader.

After initialization, `Registry.connect()` yields a context-managed writable
connection with foreign keys enabled. It refuses missing, older, inconsistent,
or unsupported schemas; callers must run `initialize()` explicitly before using
an older supported database.

## Migrations

The current schema version is **1**. Migrations are immutable plain-SQL
definitions with positive, unique versions. LifeOS sorts them by version,
requires recorded versions and names to be an exact prefix of those definitions,
and refuses unsupported future or inconsistent histories.

Each missing migration runs in its own explicit `BEGIN IMMEDIATE` transaction.
Statements execute individually, the migration record is inserted with
parameters, and the transaction commits only after every statement succeeds. A
failure rolls back that migration without rebuilding or deleting the database;
previously completed migrations remain intact.

## Version 1 tables

- `schema_migrations`: migration version, unique name, and application time.
- `files`: unique normalized vault-relative path, optional stable ID and content
  hash, file kind, size and nanosecond modification metadata, observation times,
  and soft-deletion state.
- `source_versions`: unique source/version identity, its original `files` row,
  observation time, and optional sanitization metadata. The foreign key is
  restrictive and never cascades deletion.
- `generated_outputs`: unique output identity and normalized target path,
  generator identity/version, output hash, and creation/update times. This table
  records facts only; ownership enforcement remains outside this task.

SQLite foreign-key enforcement is enabled and verified for every connection
opened by `Registry`. Timestamps use UTC RFC 3339 text with milliseconds in the
form `YYYY-MM-DDTHH:MM:SS.sssZ`. Vault and output paths use normalized,
vault-relative POSIX strings; machine-specific absolute paths and file contents
are never stored.
