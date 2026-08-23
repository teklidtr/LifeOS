# Registry

The LifeOS registry stores deterministic operational facts. It does not replace
the Markdown vault and does not store full note or attachment contents, agent
interpretations, semantic embeddings, proposal bodies, task bodies, or Graphify
state.

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

The current registry schema version is **3**. Migrations are immutable plain-SQL
definitions with positive, unique versions. LifeOS sorts them by version,
requires recorded versions and names to be an exact prefix of those definitions,
and refuses unsupported future or inconsistent histories.

The current migration sequence is:

1. `initial_registry_schema`
2. `proposals_schema`
3. `provenance_schema`

Each missing migration runs in its own explicit `BEGIN IMMEDIATE` transaction.
Statements execute individually, the migration record is inserted with
parameters, and the transaction commits only after every statement succeeds. A
failure rolls back that migration without rebuilding or deleting the database;
previously completed migrations remain intact.

## Current tables

- `schema_migrations`: migration version, unique name, and application time.
- `files`: unique normalized vault-relative path, optional stable ID and content
  hash, file kind, size and nanosecond modification metadata, observation times,
  and soft-deletion state.
- `source_versions`: unique source/version identity, its original `files` row,
  observation time, and optional sanitization metadata. The foreign key is
  restrictive and never cascades deletion.
- `generated_outputs`: unique output identity and normalized target path,
  generator identity/version, output hash, and creation/update times. This table
  records facts; canonical generated ownership remains outside SQLite.
- `proposals`: deterministic proposal index facts such as ID, status, title, and
  timestamps. Canonical proposal content remains under `proposals/<proposal-id>/`.
- `provenance_documents`: one row for each canonical Markdown file that contains
  indexed `lifeos_provenance`, including schema and generator metadata.
- `provenance_sources`: one ordered row per source snapshot in that document's
  provenance block, storing `source_index`, path, and content hash.

## Provenance indexing

Canonical generated Wiki provenance lives in Markdown frontmatter. Registry
refresh parses that frontmatter and derives one `provenance_documents` row plus
one `provenance_sources` row for each item in the ordered `sources` list.

A page with three accepted source snapshots therefore produces three source rows.
The same source path may legitimately appear more than once when its content hash
changed between accepted contributions. The row's `source_index` preserves the
canonical source order.

Registry refresh never decides ownership and never grants write authority from a
provenance record. It also does not become the source of truth for lineage: the
provenance index can be deleted and rebuilt from canonical Markdown.

See [Generated Wiki Provenance](generated-wiki-provenance.md) for the schema-v1
source-history contract.

SQLite foreign-key enforcement is enabled and verified for every connection
opened by `Registry`. Registry paths use normalized, vault-relative POSIX strings;
machine-specific absolute paths and full canonical file contents are never stored.
