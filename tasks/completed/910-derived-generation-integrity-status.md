---
id: LIFEOS-910
title: Verify active derived generation integrity
status: completed
phase: hardening
depends_on:
  - LIFEOS-902
  - LIFEOS-903
  - LIFEOS-907
risk: high
---

# Goal

Detect missing, extra, replaced, or modified files inside active graph and
export generations instead of trusting readable state metadata alone.

# Discovered integration failure

A cross-component integrity test built both a graph view and a public export,
modified active payload files directly, and expected status to fail closed:

```python
graph_active = active_generation_path(runtime / "graphify" / "knowledge")
export_active = active_generation_path(runtime / "exports" / "public-wiki")
(graph_active / "graph.json").write_text("{}")
(export_active / "wiki" / "note.md").write_text("tampered\n")

assert graph_view_status(...).status == "failed"
assert export_status(...).status == "failed"
```

The first assertion failed because graph status remained `clean`:

```text
E       AssertionError: assert 'clean' == 'failed'
```

A separate export-only reproduction confirmed that export status remained
`ready` after an exported Markdown file was modified.

Graph status currently validates `state.json` fields and current source hashes,
but not the active `graph.json` bytes. Export status validates the manifest
shape and identity, but does not verify the exported file inventory, sizes, or
rendered hashes recorded by the manifest. The generic publication pointer also
has no durable post-publication inventory that can be rechecked later.

# Why this is not an on-the-spot fix

A complete fix affects the publication contract, graph state, export manifests,
status performance, backward compatibility, and secure runtime traversal.
Simply hashing one known file would miss missing or extra files and would not
provide a reusable integrity model for all derived products.

# Scope

- Define a durable, deterministic integrity inventory for every active derived
  generation.
- Record each relative output path, exact byte size, and SHA-256 hash.
- Decide whether the inventory belongs in:
  - generic publication metadata,
  - product-specific manifests/state, or
  - both, with one authoritative verification path.
- Verify active generation inventory during graph/export status inspection.
- Reject symlinks, special files, path traversal, duplicate paths, missing
  files, unexpected extra files, and content mismatches.
- Use descriptor-relative or otherwise symlink-safe runtime traversal.
- Distinguish corrupt content from temporarily unavailable storage.
- Keep status read-only and deterministic.
- Define compatibility for generations created before the integrity inventory
  exists. Prefer an explicit `unsupported` or `rebuild-required` state over
  silently trusting old output.
- Ensure recovery and cleanup do not delete the only verifiable active
  generation.

# Out of scope

- Proving canonical source freshness; that is tracked by LIFEOS-909.
- Making derived output canonical.
- Full disk or filesystem authenticity guarantees against a privileged local
  attacker.
- Remote artifact signing or attestation.

# Required invariants

- `clean` or `ready` means every expected active payload file exists with the
  recorded bytes and no unexpected payload file exists.
- Metadata alone cannot mark a modified payload healthy.
- A symlink inside an active generation is never followed.
- Verification failures do not mutate or repair the generation.
- Graph and export status use the same integrity classification semantics.
- Repeated verification produces identical results.

# Required tests

- Modified `graph.json` changes graph status to corrupt/failed.
- Modified exported Markdown changes export status to corrupt/failed.
- Missing graph state, graph payload, export manifest, or export payload.
- Unexpected extra file in an active generation.
- File replaced by a symlink to an external path.
- FIFO, directory, socket, and other non-regular entries are rejected.
- Size mismatch and same-size hash mismatch.
- Inventory path traversal and duplicate-path corruption.
- Valid generations remain healthy.
- Pre-inventory generations require rebuild and are not silently trusted.
- Status aggregation reports affected subsystem without hiding independent
  checks.
- Verification remains read-only and does not change mtimes or active pointers.

# Acceptance criteria

- Active graph/export payload tampering is detected by product status and
  top-level `lifeos status`.
- Inventory verification is complete, deterministic, and symlink-safe.
- Existing generation compatibility is explicit and tested.
- Publication fault recovery continues to preserve one verifiable generation.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/test_publication.py tests/graph tests/exports tests/integration tests/status
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-013: Indexes are generated by scripts
- DD-018: Graphify is a helper, not authority
- DD-029: Optional purpose-specific exports
- DD-033: SQLite disposability and rebuilding
