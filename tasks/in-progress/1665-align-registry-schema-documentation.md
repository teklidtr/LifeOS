---
id: LIFEOS-1665
title: Align registry schema documentation with scoped identity migration
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-1643
risk: low
---

# Goal

Bring the registry reference into agreement with the already-shipped version 4 schema and its
scope-aware stable-identity behavior, without changing the database or identity semantics.

# Problem and current behavior

`docs/registry.md` currently declares schema version **3** and lists only
`initial_registry_schema`, `proposals_schema`, and `provenance_schema`.
`src/lifeos/registry/_migrations.py` already defines migration 4,
`scoped_stable_identity_schema`, and derives `CURRENT_SCHEMA_VERSION` from that migration.
`tests/registry/test_schema.py` explicitly asserts version 4 and a non-unique
`idx_files_stable_id` index.

Migration 4 rebuilds the physical `files`/`source_versions` tables while retaining row identities
and foreign-key relationships. It removes the physical global uniqueness restriction on
`files.stable_id` so observations of duplicate identities can be recorded and scoped resolution
can fail closed on ambiguity. The stale reference gives maintainers the wrong expected database
version and omits the distinction between recording observations and authorizing identity use.

# Scope

- Update the current version, migration sequence, and relevant table/index explanation in
  `docs/registry.md` to match the implementation and schema tests.
- Explain that a non-unique physical stable-ID index does not authorize ambiguous identity
  resolution or make the registry canonical. Retain DD-090's ID/path/content-version distinction
  and the current scoped identity resolver's fail-closed behavior.
- Search current authoritative documentation for another stale version-3 declaration or a
  conflicting global-uniqueness claim; correct only statements about the current registry.
- Preserve accurate historical completed-task evidence and migration-history examples.

# Out of scope

- SQL changes, a new migration/schema version, registry API changes, or data rewriting.
- Changing stable-ID resolution, privacy scopes, generated ownership, or canonical authority.
- A general rewrite of registry/architecture documentation.

# Acceptance criteria

- The registry reference identifies version 4 and names all four shipped migrations in order.
- Documentation accurately describes the relevant non-unique stable-ID index and scoped
  ambiguity handling, consistent with `tests/registry/test_scoped_identity_lineage.py` and DD-090.
- Per-migration transactionality, exact-prefix migration history checks, preserved row/foreign-key
  relationships, and disposable registry authority are not contradicted or weakened.
- Every factual change can be checked against current migration code/tests; no production code,
  canonical data, or historical task result is changed to make the documentation true.
- Relevant schema tests and documentation/link validation pass.

# Documentation impact

Status: required

- `docs/registry.md`: correct the current schema and migration/index description.
- Review `docs/architecture.md`'s Registry and cross-device identity sections and
  `docs/design-decisions.md` DD-090 for consistency. Change them only if another factual mismatch
  is found; do not introduce a new design decision for already-implemented behavior.
- Review `docs/user-manual/` references to registry rebuilding/schema compatibility and update
  only any current-version statements affected by this correction.

# Validation

```bash
rtk .venv/bin/pytest -q tests/registry/test_schema.py tests/registry/test_scoped_identity_lineage.py
rtk .venv/bin/python scripts/validate_manual_links.py
rtk git diff --check
```

Compare every described migration name, version, index property, and identity guarantee with
`src/lifeos/registry/_migrations.py`, the current scoped resolver, and their tests. This is a
documentation-only task; unrelated full-suite failures need not block the factual correction.

# Relevant decisions

- `AGENTS.md`: accepted decisions outrank lower-level documentation; documentation is part of
  implementation and cannot turn derived state into canonical authority.
- DD-001, DD-002, and DD-033: Markdown authority and a deterministic, rebuildable registry.
- DD-035: generated ownership remains canonical outside SQLite.
- DD-090: stable ID, current path, and observed content version are separate facts; ambiguous
  stable identity fails closed within the applicable scope.
- Completed LIFEOS-1643: cross-device identity/topology contract and scoped registry behavior.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** This is a bounded documentation correction whose source of
  truth and verification tests are already identified. Careful comparison is needed, but no
  migration design, production debugging, or architectural change is required.
