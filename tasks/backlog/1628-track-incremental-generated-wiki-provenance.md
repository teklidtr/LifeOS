---
id: LIFEOS-1628
title: Track incremental generated wiki provenance
status: backlog
phase: 16
depends_on:
  - LIFEOS-1626
risk: medium
---

# Goal

Extend canonical generated-wiki provenance so a generated file updated from a
new registered source can retain both its creation source and later ingestion
sources without conflating provenance with ownership.

# Scope

- Define a backward-compatible multi-source or update-lineage provenance schema.
- Preserve existing creation provenance when a generated-owned section update
  introduces another source.
- Keep proposal `related_sources`, generated Markdown provenance, and registry
  indexing consistent.
- Add deterministic serialization, migration, and round-trip tests.

# Out of scope

- Changing ownership authorization semantics.
- Rewriting human-owned wiki frontmatter.
- Inferring sources from links or filenames.

# Acceptance criteria

- Incrementally updated generated wiki content names every source needed to
  explain its generated claims.
- Existing schema-version-1 pages remain readable.
- Ownership and provenance remain separate canonical contracts.
