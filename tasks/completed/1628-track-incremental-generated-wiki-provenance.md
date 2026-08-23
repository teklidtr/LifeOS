---
id: LIFEOS-1628
title: Track cumulative provenance for generated wiki evolution
status: completed
phase: 16
depends_on:
  - LIFEOS-1626
  - LIFEOS-1632
risk: medium
branch: lifeos-1628-cumulative-wiki-provenance
---

# Goal

Let a generated wiki page accumulate inspectable provenance as it evolves from multiple
registered canonical sources over time, without confusing provenance with generated-file
ownership or imposing a fixed knowledge ontology.

The `lifeos_provenance` schema version 1 uses a `sources` list. LIFEOS-1628 keeps schema
version 1 and formally allows that list to accumulate multiple accepted source snapshots.
No schema migration is required because no user vault has been created with the earlier
single-source restriction.

# Design principles

- Provenance answers "what evidence and generation steps explain this generated content?"
  Ownership answers "what may LifeOS replace automatically?" They remain separate
  contracts.
- Any registered canonical Markdown source may contribute to wiki evolution. Provenance
  must not encode an assumption that knowledge originates only from `raw/` or `study/`.
- Wiki structure remains emergent. Provenance records evidence lineage, not page roles,
  folder taxonomy, or ontology.
- Proposal-local `related_sources` describes the current proposal; canonical generated
  page provenance describes cumulative lineage across accepted mutations.
- Human-owned wiki content must not gain or have its frontmatter rewritten with generated
  provenance merely because LifeOS proposed an exact-section patch.

# Scope

- Allow schema version 1 provenance to represent creation evidence plus later accepted
  source/update lineage using the existing extensible `sources` object list.
- Preserve existing creation provenance when a generated-owned wiki page receives a
  reviewed section update grounded in a new registered source.
- Define deterministic ordering/deduplication semantics: exact `(path, content_hash)`
  repeats are ignored, while the same path with a changed hash is appended as a new
  historical snapshot.
- Keep generator identity/version information sufficient to explain generated content.
- Keep proposal `related_sources`, generated Markdown provenance, registry/index parsing,
  and round-trip serialization consistent with the evolved version-1 contract.
- Add focused tests covering create → update-from-new-source → parse/serialize/reload,
  including compound/emergent wiki paths rather than fixed role folders.

# Out of scope

- Changing generated-file ownership authorization semantics.
- Rewriting human-owned wiki frontmatter to add LifeOS provenance.
- Inferring evidence from links, filenames, folder names, or semantic similarity when it
  was not part of the reviewed mutation.
- Turning provenance into a universal graph/ontology schema.
- Changing study flashcard `source_refs`, learning-context, or pedagogical-selection
  semantics except where parser compatibility with the shared provenance schema requires
  it.

# Acceptance criteria

- A generated wiki page created from source A and later updated from source B retains
  enough canonical lineage to inspect both accepted evidence contributions.
- Repeated evolution from the same path with a changed content hash has deterministic,
  explicitly tested history semantics rather than silently losing the earlier snapshot.
- Schema-version-1 provenance remains readable for both one and multiple source snapshots.
- Generated ownership and provenance remain independently validated and enforced.
- Registered sources outside `raw/` and `study/` can participate without special casing.
- Human-owned exact-section updates remain human-owned and do not acquire generated-page
  provenance automatically.
- Provenance serialization is deterministic and round-trips through Markdown parsing and
  registry/index flows.

# Documentation impact

Status: required

- `docs/user-manual/14-generated-wiki-source-history.md`: explain cumulative provenance as the generated Wiki page's inspectable References/source history.
- `docs/user-manual/README.md`: make that user-facing documentation discoverable.
- `docs/generated-wiki-provenance.md`: define the canonical schema-v1 merge, ownership-separation, and failure contract.
- `docs/data-model.md`: record the generated Wiki provenance frontmatter model and cumulative snapshot semantics.
- `docs/registry.md`: document schema-v3 provenance tables and multi-source ordered indexing; this also corrects stale registry schema documentation discovered while documenting LIFEOS-1628.
- `docs/design-decisions.md` was reviewed. No new DD is required because LIFEOS-1628 formalizes the existing provenance-versus-ownership boundary and existing schema-v1 `sources` object-list contract rather than introducing a new independent system principle.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/ingestion tests/wiki tests/registry
uv run pytest --import-mode=importlib -q
```

# Relevant decisions

- LIFEOS-1632 made wiki structure agent-directed and emergent; provenance must remain
  orthogonal to page layout.
- LIFEOS-1633 allows any registered canonical Markdown source to ground wiki evolution.
- Mutation policy stays strict even while semantic organization remains flexible.
- 2026-08-23: keep `schema_version: 1`; retain `sources` as a list of extensible source
  objects rather than flattening paths into a scalar list.

# Evidence

- PR: #5 (`LIFEOS-1628: Track cumulative generated-wiki provenance`).
- GitHub Actions CI passed Ruff, mypy, Python compilation, and manual-link validation before the documentation gate was introduced.
- Full test suite passed: 1516 tests before rebasing onto the documentation-gate master.
- Docker clean-room setup and MCP gate passed.
- After LIFEOS-1635 merged, the rebased PR correctly failed the new documentation-impact gate until this section and the affected docs were added.
