# Generated Wiki Provenance

Generated Wiki provenance is the canonical, inspectable record of which source snapshots have contributed to a LifeOS-generated Wiki page.

A useful mental model is an academic paper's **References** section: the Wiki page is the evolving synthesis, while `lifeos_provenance.sources` records the canonical source snapshots that have actually contributed to that generated page.

Provenance is not ownership. Provenance answers **where did this generated knowledge come from?** Generated ownership answers **may LifeOS replace this file automatically?** The two contracts are validated independently.

## Canonical frontmatter

Schema version 1 uses an extensible list of source objects:

```yaml
lifeos_provenance:
  schema_version: 1
  sources:
    - path: notes/creatine.md
      content_hash: sha256:1111111111111111111111111111111111111111111111111111111111111111
    - path: journal/2026-08-23.md
      content_hash: sha256:2222222222222222222222222222222222222222222222222222222222222222
    - path: papers/creatine-review.md
      content_hash: sha256:3333333333333333333333333333333333333333333333333333333333333333
  generator:
    id: lifeos-ingestion
    version: "1"
    prompt_schema_version: "1"
    model_id: example-model
  created_at: "2026-08-23T20:00:00Z"
```

The `sources` collection is deliberately a list of objects rather than a flat path list. Today each entry requires `path` and `content_hash`; the object shape leaves room for future source metadata without redesigning the surrounding provenance structure.

## Cumulative source history

When a generated-owned Wiki page is created from source A, its provenance starts with A. If a later reviewed update is grounded in source B, the accepted candidate retains A and appends B.

The merge rules are deterministic:

- an exact `(path, content_hash)` repeat is ignored;
- the same path with a different content hash is appended as a distinct historical snapshot;
- accepted source order is preserved;
- the existing generator metadata and original provenance `created_at` are preserved when another source snapshot is appended.

Keeping the old hash when the same source path changes means provenance records the source version that participated in each accepted evolution, rather than pretending the current file bytes were always the evidence.

## Generated and human-owned pages

Cumulative provenance is updated only when the target is already classified as generated-owned and the normal ownership/hash checks permit a generated-file replacement.

A human-owned Wiki page can still receive a reviewed exact-section patch, but LifeOS does not add generated provenance to that page merely because an ingestion proposal used it as a target.

Likewise, generated ownership does not get inferred from provenance. A provenance block is evidence lineage, not write authority.

If a generated-owned page has no provenance block, LifeOS does not invent missing history during an update. The file remains governed by the independent generated-ownership contract.

## Proposal-local sources versus page history

A proposal's `related_sources` describes the source or sources involved in that proposal. The generated page's `lifeos_provenance.sources` describes cumulative accepted lineage across the page's lifetime.

Those concepts intentionally differ. A proposal updating a page from source B can have B as its current related source while the resulting page provenance records A, B, and earlier accepted source snapshots.

## Multi-source target grounding

One folder-ingestion proposal may verify many source snapshots, but provenance is still target-specific. Each reconciled target mutation names the subset of verified `(path, content_hash)` snapshots that actually support that target. A new generated page starts with that subset, and a generated-owned replacement merges that subset into the page's existing accepted source history using the same deterministic deduplication rules above.

The proposal-level `related_sources` field is the deterministic union of selected batch sources. It must not be interpreted as evidence that every source contributed to every target. The digest-bound ingestion review metadata records the target-to-source grounding map so reviewers can distinguish batch membership from page-specific evidence lineage without storing hidden reasoning.

## Registry indexing

The registry derives provenance rows from canonical Markdown. One generated page produces one provenance document record plus one ordered source row per entry in `lifeos_provenance.sources`.

The source index preserves canonical order. Registry state is rebuildable; the Markdown frontmatter remains the source of truth for provenance.

## Failure behavior

Canonical provenance is strict and fails closed when present but malformed. Schema version 1 requires:

- a non-empty `sources` list;
- normalized vault-relative POSIX source paths;
- canonical `sha256:<64 lowercase hex>` content hashes;
- generator `id`, `version`, and `prompt_schema_version` fields;
- an optional non-empty `model_id`;
- `created_at` in `YYYY-MM-DDTHH:MM:SSZ` form.

Unknown provenance/source/generator fields are currently rejected. Future metadata additions therefore require an explicit schema-contract change rather than being silently accepted.
