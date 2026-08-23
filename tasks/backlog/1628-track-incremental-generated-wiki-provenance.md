---
id: LIFEOS-1628
title: Track cumulative provenance for generated wiki evolution
status: backlog
phase: 16
depends_on:
  - LIFEOS-1626
  - LIFEOS-1632
risk: medium
---

# Goal

Let a generated wiki page accumulate inspectable provenance as it evolves from multiple
registered canonical sources over time, without confusing provenance with generated-file
ownership or imposing a fixed knowledge ontology.

The current `lifeos_provenance` schema version 1 requires exactly one source snapshot.
That is sufficient for first creation, but a later reviewed section update grounded in a
different source can change generated knowledge without preserving that additional
lineage in the canonical page.

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

- Define a backward-compatible provenance evolution from schema version 1 that can
  represent creation evidence plus later accepted source/update lineage.
- Preserve existing creation provenance when a generated-owned wiki page receives a
  reviewed section update grounded in a new registered source.
- Define deterministic ordering/deduplication semantics for repeated source paths and
  changed source hashes so lineage remains inspectable rather than silently collapsing
  history.
- Keep generator identity/version information sufficient to explain creation and later
  generated mutations.
- Keep proposal `related_sources`, generated Markdown provenance, registry/index parsing,
  and round-trip serialization consistent with the evolved schema.
- Maintain read compatibility for existing schema-version-1 generated wiki pages and
  other documents that already use `lifeos_provenance`.
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
- Existing schema-version-1 provenance remains readable.
- Generated ownership and provenance remain independently validated and enforced.
- Registered sources outside `raw/` and `study/` can participate without special casing.
- Human-owned exact-section updates remain human-owned and do not acquire generated-page
  provenance automatically.
- Provenance serialization is deterministic and round-trips through Markdown parsing and
  registry/index flows.

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
