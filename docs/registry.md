# Registry

The LifeOS registry stores deterministic operational facts. It does not replace
the Markdown vault and does not store full note or attachment contents, agent
interpretations, semantic embeddings, proposal bodies, task bodies, or Graphify
state.

## Location and initialization

Callers choose the database path explicitly. The shipped CLI and MCP runtime use:

```python
registry = Registry(config.runtime_dir / "registry.db")
```

With the first-party `lifeos init` defaults, this resolves to
`.lifeos/registry.db` inside the vault.

Importing `lifeos.registry`, constructing `Registry`, reading migration metadata,
and loading configuration do not create files. `Registry.initialize()` is the
explicit schema-initialization operation used by registry workflows: it may create
the database's direct parent and the SQLite file, then applies missing migrations.
Configuration loading itself remains read-only.

After initialization, `Registry.connect()` yields a context-managed writable
connection with foreign keys enabled. It refuses missing, older, inconsistent,
or unsupported schemas; callers must run the supported initialization/refresh
workflow before using an older supported database.

## Migrations

The current registry schema version is **4**. Migrations are immutable plain-SQL
definitions with positive, unique versions. LifeOS sorts them by version,
requires recorded versions and names to be an exact prefix of those definitions,
and refuses unsupported future or inconsistent histories.

The current migration sequence is:

1. `initial_registry_schema`
2. `proposals_schema`
3. `provenance_schema`
4. `scoped_stable_identity_schema`

Migration 4 rebuilds the physical `files` and `source_versions` tables while
preserving their row IDs and the `source_versions.original_file_id` foreign-key
relationships. It replaces the original global SQLite uniqueness constraint on
`files.stable_id` with the non-unique partial `idx_files_stable_id` index. This
lets the disposable registry retain observations needed by scoped identity
reconciliation without treating a duplicate observation as authorization to use
that identity.

Stable-ID use still fails closed on ambiguity. Registry scan preflight refuses
duplicate stable IDs in the participating canonical Markdown observations, and
`resolve_registered_stable_id()` refuses to resolve a stable ID when more than
one active registry row carries it. A stable ID identifies which canonical note
was observed, its vault-relative path records where that note was observed, and
its content hash records which version was observed; those registry mappings are
rebuildable facts, not canonical authority.

Each missing migration runs in its own explicit `BEGIN IMMEDIATE` transaction.
Statements execute individually, the migration record is inserted with
parameters, and the transaction commits only after every statement succeeds. A
failure rolls back that migration without rebuilding or deleting the database;
previously completed migrations remain intact.

## Current tables

- `schema_migrations`: migration version, unique name, and application time.
- `files`: unique normalized vault-relative path, optional stable ID indexed by
  non-unique `idx_files_stable_id`, optional content hash, file kind, size and
  nanosecond modification metadata, observation times, and soft-deletion state.
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

## Refresh surfaces

The supported `lifeos scan` CLI command and MCP `registry_refresh` facade refresh
the disposable **file and proposal indexes**. They initialize the registry schema
when necessary, reconcile file observations, and rebuild proposal index rows. They
do not change canonical Markdown or generated ownership.

## Mutation authority after registry loss

Deleting, reinitializing, or rebuilding `.lifeos/registry.db` cannot increase
proposal or application authority. Proposal lifecycle state, reviewed proposal
content and digests, current target bytes and hashes, and generated ownership in
`system/generated-ownership.json` remain authoritative outside SQLite.

A stale or conflicting proposal therefore remains stale or conflicting when the
registry is absent and after a supported refresh rebuilds its indexes. Rebuilding
the proposal index derives lifecycle status from canonical proposal artifacts; it
does not reset terminal history, repair ownership, rewrite targets, or turn
registry observations into authorization for a canonical write.

Provenance indexing is a separate deterministic registry operation exposed in
Python as `refresh_provenance_index()`. It scans Git-tracked canonical Markdown,
parses `lifeos_provenance`, and derives one `provenance_documents` row plus one
`provenance_sources` row for each item in the ordered `sources` list. Do not assume
that `lifeos scan` refreshes this separate provenance index.

A page with three accepted source snapshots therefore produces three source rows
when the provenance index is refreshed. The same source path may legitimately
appear more than once when its content hash changed between accepted contributions.
The row's `source_index` preserves the canonical source order.

Provenance indexing never decides ownership and never grants write authority from
a provenance record. It also does not become the source of truth for lineage: the
provenance index can be deleted and rebuilt from canonical Markdown.

See [Generated Wiki Provenance](generated-wiki-provenance.md) for the schema-v1
source-history contract.

SQLite foreign-key enforcement is enabled and verified for every connection
opened by `Registry`. Registry paths use normalized, vault-relative POSIX strings;
machine-specific absolute paths and full canonical file contents are never stored.
