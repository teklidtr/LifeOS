---
id: LIFEOS-201
title: Canonical ingestion provenance contract
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-100, LIFEOS-111]
risk: low
---

# Objective
Define how a generated wiki page canonically records the study source and generation context from which it was derived.

# Scope
- Define a canonical provenance representation stored in Git-tracked Markdown frontmatter.
- The contract must include: source vault path, source content hash, ingestion/generator identifier, generator version, creation timestamp.
- Define how multiple source documents are represented (use a list for `sources` even though the first slice supports exactly one).
- Evaluate whether the frontmatter parser and canonical serializer support nested mappings, lists of mappings, deterministic key order, and canonical timestamp/hash serialization.
- Document compatibility with generated-file ownership.

# Expected files
- `src/lifeos/ingestion/__init__.py`
- `src/lifeos/ingestion/provenance.py`
- `tests/ingestion/test_provenance.py`

# Non-goals
- SQLite migration
- AI invocation or CLI command
- Proposal approval or application
- Provenance graph visualization

# Acceptance criteria
- Provenance survives deletion of `.lifeos/` and `registry.db`.
- Source path and source hash are preserved canonically.
- Representation is deterministic and valid Git-tracked Markdown metadata.
- SQLite is explicitly classified as a derived index.
- Compatibility with generated-file ownership is documented.

# Focused test plan
- deterministic serialization
- parse and serialize round trip
- one-source validation
- malformed path rejection
- malformed hash rejection
- unsupported schema version
- provenance survives deletion of all disposable state
- compatibility with generated ownership without conflating the two models

Implementation has not begun.
