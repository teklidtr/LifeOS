---
id: LIFEOS-1725
title: Integrate identity and relocation coherence into the retrieval index service
status: completed
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

- [x] One statically resolvable `RetrievalIndexService` supplies the effective behavior for every public/imported construction path; no coherence subclass or module-level chunking replacement remains.
- [x] The currently active retriever uses that service directly without instantiating then replacing a base service; other search behavior stays unchanged for LIFEOS-1726.
- [x] Rebuild, incremental sync, health/recovery, stable-identity, rename/move, interrupted relocation, privacy, and legacy rename-reporting tests retain equivalent assertions.
- [x] Existing public exports, call/return shapes, progress/error behavior, and private fault-injection seams receive a repository-wide dependency audit and compatible migration.
- [x] Obsolete service/chunking glue disappears without creating a second persistence/identity model. Record removed concepts and net production change separately from retained recovery logic.

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

# Completion evidence

Implemented against current HEAD `7b23412` on `lifeos-1725-retrieval-index-coherence`.
The initial checkout had no tracked changes; the pre-existing untracked `.serena/`
directory was preserved and excluded from the commit. The task was promoted through
ready and in-progress before implementation. LIFEOS-1726 remains in backlog.

## Implementation and compatibility audit

- `retrieval.service.RetrievalIndexService` is the sole implementation. Package,
  direct service, legacy coherence-service, and search-module imports resolve to
  that class. The active hybrid retriever constructs exactly one index service.
- Rebuild and incremental synchronization pass the policy-visible source identity
  plan explicitly to `chunk_markdown_file(expected_document_id=...)`. Existing
  chunking arguments and default behavior remain valid; the existing
  `reidentify_note` algorithm preserves persisted document/chunk identity rules.
- `_sync_sources` contains the existing incremental algorithm with explicit source
  and identity inputs. No alternate service or second persistence model remains.
- Serena symbol/reference analysis and repository-wide searches covered direct
  constructions, exports, chunking callers, changed helpers, monkeypatch targets,
  return shapes, and errors. The two coherence-service fault-injection imports
  moved to `service.read_vault_markdown` and `service.chunk_markdown_file` without
  weakening their assertions. The obsolete eager-traversal test seam now checks
  the actual read boundary, including exactly one canonical health read and no
  runtime content reads.
- Added import/constructor coverage and a three-note relocation cycle through
  package, direct, and legacy imports, verifying document/chunk identities,
  public result paths, health, and staging cleanup. Existing swap, occupied
  destination, interruption, legacy rename, privacy, and identity tests remain.
- AST comparison with HEAD confirmed all 12 moved identity/relocation helpers and
  15 unaffected service methods/functions retain identical logic. The effective
  source filter is unchanged apart from deleting the temporary source-cache path.
  Rebuild and incremental core logic is unchanged after accounting for explicit
  source/identity inputs. Search methods are unchanged; its constructor only loses
  the redundant service import/replacement.

## Removed concepts and retained recovery logic

Removed the alternate subclass, runtime class/chunker replacement, ambient
`ContextVar` identity map, temporary service source cache, wrapper rebuild method,
obsolete eager source filtering, and redundant retriever service construction.
The legacy module is now a three-line ordinary compatibility re-export.

Across the five changed production files, physical lines decreased from 2,050 to
1,955: **95 net lines removed**. This is separate from retained identity/recovery
logic: all 12 existing static helpers (163 nonseparator lines) were moved intact.
Relocation reservations, SQLite backup staging, destination parking, public-path
restoration, interrupted-result suppression, and atomic publication remain in the
single service. No schema, identity semantics, provider contracts, or ranking
rules changed.

## Documentation and discoverability review

Updated both required architecture documents with the single service's ownership
and explicit identity flow. Reviewed
`docs/user-manual/11-semantic-retrieval-and-knowledge-conversations.md`,
`docs/cross-device-vault-coherence.md`, and DD-033/060/061/062/066/089/090; their
user behavior and contracts remain accurate, so no edits were needed there.
No semantic capability, Explore, bridge, CLI, MCP, configuration, or operational
behavior changed; capability definitions and setup instructions remain accurate.

## Validation results

- Retrieval/coherence/context suites: **140 passed, 1 platform skip**; the final
  full run includes all 55 retrieval tests, 20 coherence tests, and 66 context tests.
- Required facade/MCP/integration/doctor suite: **368 passed, 4 platform skips**.
- Full local pytest: **2,488 passed, 12 platform skips** (2,500 collected), with
  zero failures or errors. The skips require Linux `/proc/self/fd` or a
  case-sensitive filesystem.
- Ruff check and format check passed repository-wide (538 files formatted).
- Mypy passed all 235 source files; compileall, task workflow validation, manual
  links, documentation-impact evaluation, and `git diff --check` passed.

Validation used the repository's installed `.venv` tools where the sandbox blocked
uv's cache; elevated `uv run` was used for the final full suite. The unversioned
`python` shim cannot resolve the repository's `3.11` selection, so script checks
used `.venv/bin/python`. macOS default `/private` temp paths triggered two existing
privacy-test path guards. A subsequent nested test directory interfered with Git
non-repository detection, and sandboxing blocked a Unix socket fixture. The final
full run used elevated access and a fresh temp directory outside both `/private`
and this Git checkout; all those failures resolved without unrelated code edits.

Local privacy/identity/relocation/determinism and compatibility audits passed.
No PR was opened or merged. The PR-only normal/security review, plugin, and GitHub
full-validation checkpoints remain required before any future PR is merged.
LIFEOS-1726 can build on the direct service binding; its search scoring and
privacy/identity wrappers were deliberately left in place.
