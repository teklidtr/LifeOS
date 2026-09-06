---
id: LIFEOS-1732
title: Make ingestion composition and provenance explicit
status: ready
phase: hardening
depends_on:
  - LIFEOS-1731
risk: high
---

# Goal

Make ingestion proposal behavior follow ordinary imports and explicit data flow, eliminating module substitution and ambient source injection while preserving existing APIs and provenance semantics.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `src/lifeos/ingestion/proposals.py` wraps `_proposals_core.py`, saves original builder/persistence functions, mutates core attributes, and assigns `sys.modules[__name__] = _core`. `_with_source` sets/resets `_current_source`, a `ContextVar`, so `_build_wiki_section_operation` can add cumulative provenance indirectly. `_bind_existing_target_identities` and prepublication checks also live in this effective composition. Revalidate after the publisher migration.

# Scope

- Trace build/persist APIs for wiki creation, section updates, compound/compounding proposals, and study learning through facade, multi-source, research, and MCP callers.
- Put the effective builder, provenance, identity-binding, and persistence behavior in ordinary definitions and imports. A small explicit public re-export facade is acceptable; dynamic module substitution and mutation of imported implementations are not.
- Pass source/provenance inputs explicitly through the internal operation-building path; remove `_current_source`, `_with_source`, saved-original wrappers, and import-time core replacement.
- Retain the shared publisher from LIFEOS-1731 without redesigning it. Remove obsolete bodies and aliases only after a repository-wide compatibility search.

# Out of scope

- Changing cumulative provenance, evidence selection, taxonomy, ownership classification, stable identity policy, proposal formats, or public build/persist signatures.
- Rewriting Markdown parsing or replacing typed boundaries with new dependencies. Serialized proposal/review bytes remain intentional validation boundaries where current contracts require them.

# Required invariants

- Preserve cumulative generated-wiki provenance, deterministic source ordering/deduplication, metadata hashes, exact Markdown/section behavior, and multi-source grounding. Provenance from one operation must not leak into another operation or invocation.
- Preserve source authorization/current-hash verification, runtime/protected exclusions, canonical ownership checks, and immediate prepublication revalidation.
- Preserve stable target identity, reviewed path/base hash, stale/ambiguous rejection, create-target absence checks, and immutable review-digest binding.
- Keep public names, signatures, result/document types, exception types/messages, and direct callers compatible. Deliberate changes to private injection targets require a complete caller/test migration with equivalent failure coverage.

# Acceptance criteria

- [ ] All production ingestion builder/persist call paths use static definitions/imports; no module substitution, cross-module rebinding, or saved-original dispatch remains in this composition.
- [ ] Provenance inputs are explicit at the operation boundary, with no ambient `ContextVar` or replacement global state used to supply them.
- [ ] Existing single-source, cumulative, compound, study, and multi-source outputs and error semantics remain covered; meaningful tests demonstrate nested/interleaved invocation isolation where relevant.
- [ ] All public exports and known patch points are audited, and every unavoidable private-seam migration is recorded.
- [ ] Obsolete implementations/wrappers disappear; the change does not replace them with a service locator, dependency-injection framework, or generalized builder hierarchy.
- [ ] Record removed concepts/symbols and net production change. Retain semantic/privacy/security tests; replace only obsolete machinery assertions with equivalent boundary coverage.

# Documentation impact

Status: required
- `docs/architecture.md`: describe explicit ingestion proposal composition and source/provenance ownership.
- `docs/mcp-exploration-architecture.md`: align any ingestion implementation references while preserving the documented runtime and multi-source contracts.

# Validation

```bash
uv run pytest -q tests/ingestion tests/facade tests/proposals
uv run pytest -q tests/mcp tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Include cumulative provenance, proposal-root hardening, ingestion source/target privacy, multi-source ingestion, and real MCP ingestion lifecycle regressions. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-079, DD-081, DD-083, DD-084, DD-087, DD-090, and DD-092: MCP ingestion authority, ownership, immutable review, taxonomy, runtime policy, identity, and multi-source semantics.

# Implementation size and sequencing

Medium. Depends on LIFEOS-1731 because both tasks touch ingestion persistence; this task owns builder/import/provenance composition, not publication mechanics. Independent of MCP representation consolidation because public facade APIs remain stable.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** Ambient state and import-time substitution obscure provenance and identity behavior across several public paths. Sol with high reasoning provides appropriate semantic analysis for this bounded module consolidation; Serena references should establish the effective call graph before edits.
