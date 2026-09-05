---
id: LIFEOS-1725
title: Integrate identity and relocation coherence into the retrieval index service
status: backlog
phase: hardening
depends_on: []
risk: high
---

# Goal

Put identity-aware indexing and relocation recovery in the actual retrieval index implementation, eliminating its runtime function replacement and alternate service implementation.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `src/lifeos/retrieval/coherence_service.py` subclasses `service.RetrievalIndexService` and replaces the service module's `chunk_markdown_file` using `setattr`. Serena inspection found `_identity_plan`, `_coherent_chunk_markdown_file`, `_identity_relocations`, `_stage_index_snapshot`, `_park_identity_relocations`, `_restore_public_paths`, `_suppress_unproven_relocations`, and overrides of `_allowed_sources`, `rebuild`, and `incremental_sync`. Package exports select the coherence service; `coherence_search.HybridRetriever.__init__` replaces the base index service with it.

# Scope

- Integrate the effective source filtering, identity/chunk identification, rebuild, incremental sync, and relocation logic into `retrieval/service.py` and the existing chunking/index owners where the behavior belongs.
- Replace runtime chunking substitution with explicit ordinary calls and parameters while preserving existing public call shapes.
- Remove the alternate `RetrievalIndexService` subclass and obsolete service implementations; update package exports and current retriever construction to use the single service directly.
- Keep relocation staging/parking/recovery helpers as ordinary implementation details where necessary. A cohesive static helper module is acceptable; an alternative service layer is not.
- Preserve old import paths through ordinary aliases/re-exports only where compatibility requires them. Inventory direct class/module users and monkeypatch targets before deletion.

# Out of scope

- Search scoring/authorization wrapper removal (LIFEOS-1726), a new retrieval backend, changes to persisted schema or identity semantics, or a generalized relocation framework.
- Removing essential parked-path/staging recovery behavior merely because it is lengthy.

# Required invariants

- Markdown remains authoritative; index/embedding state remains disposable, local, and rebuildable. Stable ID, current path, and content hash remain distinct facts.
- Preserve policy-before-source-read/provider influence, runtime/protected exclusions, stable-ID ambiguity handling, and identity verification against canonical state.
- Preserve transactional staging/publication, interrupted relocation recovery, path swaps/cycles/collisions, no public leakage of temporary parked paths, and conservative reporting of unproven relocations.
- Preserve deterministic document/chunk identity, ordering, manifests, progress/results/errors, provider invocation/cache behavior, and existing index compatibility/rebuild behavior.

# Acceptance criteria

- [ ] One statically resolvable `RetrievalIndexService` supplies the effective behavior for every public/imported construction path; no coherence subclass or module-level chunking replacement remains.
- [ ] The currently active retriever uses that service directly without instantiating then replacing a base service; other search behavior stays unchanged for LIFEOS-1726.
- [ ] Rebuild, incremental sync, health/recovery, stable-identity, rename/move, interrupted relocation, privacy, and legacy rename-reporting tests retain equivalent assertions.
- [ ] Existing public exports, call/return shapes, progress/error behavior, and private fault-injection seams receive a repository-wide dependency audit and compatible migration.
- [ ] Obsolete service/chunking glue disappears without creating a second persistence/identity model. Record removed concepts and net production change separately from retained recovery logic.

# Documentation impact

Status: required
- `docs/semantic-retrieval-conversation-architecture.md`: document the single index service and its identity/relocation recovery ownership.
- `docs/architecture.md`: align retrieval coherence implementation references.
- Review `docs/user-manual/11-semantic-retrieval-and-knowledge-conversations.md`; index/recovery behavior remains unchanged.

# Validation

```bash
uv run pytest -q tests/retrieval
uv run pytest -q tests/facade tests/mcp tests/integration tests/cli/test_doctor_coherence.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Include `test_coherence_runtime_and_moves.py`, `test_interrupted_relocation_result.py`, `test_legacy_rename_reporting.py`, and existing index/privacy/recovery tests. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-033, DD-060, DD-061, DD-062, DD-066, DD-089, and DD-090: disposable retrieval state, privacy/provider neutrality, one writer, and identity/path/version separation.

# Implementation size and sequencing

Medium to large: one index service and its tightly coupled relocation/chunking behavior. Independent foundation for LIFEOS-1726, which owns search/ranking integration after service replacement is gone.

# Recommended Model

- **Recommended model/configuration:** `gpt-6-astra`, reasoning effort `high`.
- **Reason for the recommendation:** Relocation cycles, interrupted state restoration, canonical identity verification, and privacy interact across derived persistence. Astra with high reasoning is justified to avoid deleting recovery behavior while collapsing the implementation layers.
