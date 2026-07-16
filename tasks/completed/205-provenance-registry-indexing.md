---
id: LIFEOS-205
title: Provenance registry indexing and queries
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-201]
risk: medium
---

# Objective
Index canonical wiki provenance into disposable SQLite tables for fast queries.

# Scope
- Add next Python migration in `src/lifeos/registry/_migrations.py`.
- Derived table may include fields like `derived_path`, `source_path`, `source_hash`, `generator_id`, `generator_version`, `created_at`.
- Index only canonical applied wiki pages carrying valid LIFEOS-201 provenance.
- Define how provenance-bearing pages are discovered.
- Provide separate typed read queries; maintain separation of read/write services.

# Expected files
- `src/lifeos/registry/_migrations.py`
- `src/lifeos/registry/provenance.py`
- `tests/registry/test_provenance.py`

# Non-goals
- Canonical provenance storage in SQLite
- Proposal creation, AI analysis, CLI ingestion
- Modifying wiki pages during scans

# Acceptance criteria
- Applied provenance-bearing wiki page is indexed.
- Malformed provenance aborts refresh without partial replacement.
- Deleting `registry.db` and rescanning restores rows from Markdown.
- Removing canonical derived page removes indexed rows.
- No canonical Markdown is modified; SQLite is never used to recreate metadata.

# Focused test plan
- fresh schema and upgrade
- valid canonical provenance indexed
- multiple source rows from one derived page
- malformed provenance aborts refresh
- failed refresh preserves previous rows
- removed page reconciled
- deterministic queries
- database deletion and rebuild
- no canonical writes

# Evidence
- implementation commit hash: adc641cb4c8af00d317de8f0d4ac4c9a89da33a4
- focused and full-suite counts: 13 focused tests, 416 full suite.
- Ruff and mypy passed
- migration 3 preserves existing registry data
- canonical Markdown is the provenance source of truth
- all parsing completes before the write transaction
- failed refresh preserves the previous complete index
- missing tracked files abort refresh
- registry deletion and rebuild restore identical typed results
- queries are read-only and never migrate
- Markdown and generated ownership remain unchanged
