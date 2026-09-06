---
id: LIFEOS-1726
title: Integrate privacy and identity coherence into the hybrid retriever
status: completed
phase: hardening
depends_on:
  - LIFEOS-1725
risk: high
---

# Goal

Make the actual hybrid retriever own its authorization, identity verification, and evidence behavior, removing the alternate coherence retriever and redundant evidence layer without weakening privacy-before-influence.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `retrieval/coherence_search.py` defines an alternate `HybridRetriever` over `retrieval/search.py` plus `StableRetrievalEvidence`. Important symbols are `search`, `_index_health`, `_preauthorization_paths`, `_in_scope`, `_authorize_candidates`, `_verified_current_stable_id`, and `_with_stable_id`. `retrieval/__init__.py` exports the coherence classes. Facade/MCP context and conversation consumers receive results from that composition. Revalidate after LIFEOS-1725 integrates the index service.

# Scope

- Integrate the effective authorization/candidate/ranking path into `retrieval/search.py` so public construction and direct module imports select the same implementation.
- Consolidate evidence representation with the authoritative retrieval evidence type where compatible; remove an evidence subclass/projection that merely adds verified identity after the fact.
- Preserve verified identity as an explicit result of authorized canonical inspection, not as a trusted index attribute. Retain separate data only when it encodes a necessary trust distinction.
- Remove obsolete retriever methods, wrapper construction, and redundant exports. Keep ordinary aliases for intentional import compatibility where needed.
- Audit ranking helpers, provider calls, index/cache access, and downstream facade/context/conversation consumers before deciding the final enforcement boundary.

# Out of scope

- Index/relocation implementation changes already owned by LIFEOS-1725, ranking formula changes, new search dependencies, retrieval benchmarks as a separate project, or general DTO cleanup outside retrieval.
- New policy abstractions or retaining a base retriever and a second policy wrapper as parallel implementations.

# Required invariants

- Policy must hold before protected/excluded content can influence candidate generation, lexical corpus statistics, ranking, graph/embedding signals, provider invocation, caches, or output. Filtering the final results is insufficient.
- Preserve explicit protected-scope intent, runtime exclusion, local/external disclosure rules, safe reads, and fail-closed policy/identity checks.
- Preserve canonical verification of stable IDs/current paths/content versions, duplicate/ambiguous-ID behavior, and relocation results from the integrated index service.
- Preserve ranking formulas, tie-breaks, deduplication, deterministic evidence order, response fields/types, diagnostics, errors, provider/cache effects, and direct public construction/import compatibility.

# Acceptance criteria

- [x] All public retriever entry points reach one static implementation; the coherence subclass and redundant evidence wrapper are removed or reduced to ordinary compatibility aliases with no behavior.
- [x] One visible authorization flow enforces policy before every relevant influence boundary without leaving the old path reachable through direct imports.
- [x] Existing privacy-before-influence, runtime-query, stable-identity exposure, ranking, provider, relocation, and context-consumer tests retain equivalent behavior coverage.
- [x] Verify that denied content cannot alter visible ranking/corpus statistics or trigger provider reads, including alternate candidate paths. Preserve existing adversarial tests and add only material missing coverage exposed by the migration.
- [x] Audit all renamed helpers, imported classes, constructor/return shapes, accessed attributes, patch points, and exact error strings; preserve compatibility or migrate justified private seams completely.
- [x] Record removed concepts and conservative net production change. Essential privacy and verified-identity logic remains explicitly owned and reviewable.

# Documentation impact

Status: required
- `docs/semantic-retrieval-conversation-architecture.md`: document the single retriever, privacy-before-influence flow, and verified evidence ownership.
- `docs/architecture.md`: align retrieval/context implementation references.
- Review `docs/mcp-exploration-architecture.md` and the retrieval user manual for affected consumer references; public behavior is unchanged.

# Validation

```bash
uv run pytest -q tests/retrieval
uv run pytest -q tests/conversations tests/facade tests/mcp tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Include security-review privacy, runtime-query privacy, stable-identity exposure, hybrid search, and MCP hybrid-context regressions. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-014, DD-060, DD-061, DD-062, DD-066, DD-087, DD-089, and DD-090: composed navigation, disposable state, privacy/provider boundaries, runtime context, and identity.

# Implementation size and sequencing

Medium. Depends on LIFEOS-1725 to avoid competing edits to service construction and package exports; this task owns search authorization/ranking/evidence composition only.

# Recommended Model

- **Recommended model/configuration:** `gpt-6-astra`, reasoning effort `high`.
- **Reason for the recommendation:** Privacy depends on preventing influence before ranking and provider access, not simply on visible output filtering. Astra with high reasoning is justified for tracing those indirect paths while merging the retriever and verified-identity representation.

# Completion evidence

Implemented from merged master HEAD `40b2a4326981cc890cec5a3e1f8f5d0605f4d972`
on `lifeos-1726-retriever-privacy-identity-coherence`. HEAD contains the merged
LIFEOS-1725 commit `6fda2c6` and its completed task. The initial tracked working
tree was clean; pre-existing untracked `.serena/` remains excluded. This task
moved through ready and in-progress before implementation.

## Implementation and authorization ownership

- `retrieval.search.HybridRetriever` now owns the effective search implementation.
  Package, direct-module, and legacy imports resolve to that single class.
  `coherence_search.py` contains only compatibility imports and `__all__`.
- One explicit `_QueryAuthorization` value belongs to each search. It replaces
  seven ambient context variables and their reset/capture scaffolding while
  retaining query-local row verification, scoped support, and identity candidates.
  This is temporary query state, not a new policy framework or persisted model.
- Metadata policy/runtime/stale-path selection precedes canonical reads. The first
  hash check admits only query-influencing current rows to scoring and semantic
  computation. The second check revalidates candidates and link support before
  reranking/evidence exposure, then recomputes link scores from surviving support.
  Both checks remain: they close different timing windows.
- `RetrievalEvidence` now directly includes optional `stable_id`, populated during
  construction from the second canonical hash check, healthy uniqueness proof,
  and final scope decision. `StableRetrievalEvidence` is an ordinary alias. No
  subclass or post-search evidence projection remains.
- LIFEOS-1725's `service.py`, `coherence_service.py`, `chunking.py`, and `index.py`
  remain byte-identical to merged HEAD. The retriever still constructs its single
  integrated index service normally. No schema, relocation, or index behavior changed.

## Compatibility and invariant audit

Serena symbol/reference analysis and repository-wide searches covered public and
private import paths, constructor/search signatures, evidence consumers in Context
Packs and conversations, facade/MCP callers, provider/disclosure gates, index and
embedding access, ranking helpers, monkeypatch seams, and explicit errors.

The former metadata-only `_in_scope` is now `_matches_scope`; canonical `_in_scope`
and `_authorize_candidates` receive explicit query state, `_preauthorization_paths`
receives stale paths, and `_verified_current_stable_id` receives a path rather than
requiring a preliminary evidence object. All known private callers were migrated.
The canonical-read monkeypatch in `test_stable_identity_exposure.py` now targets
`retrieval.search.read_vault_markdown`; its two-read and unrelated-note assertions
are unchanged. The old no-op authorization method, wrapper search/health methods,
base-class alias, runtime class replacement, and `_with_stable_id` projection are gone.

AST comparisons confirmed all nine ranking/deduplication/cosine helpers are
unchanged, as are ranking components, response serialization, stable-ID extraction,
service health delegation, public constructor/search parameter shapes, and every
explicit raised error expression. The metadata scope predicate changed only its
name. Existing privacy, identity, relocation, provider, and consumer regressions
retain their assertions.

Six added regression cases cover single-class/single-evidence imports, denied
protected/excluded/runtime rows with embedding/link/graph signals through all three
construction paths, nested-query isolation, and a relocation during query embedding.
Denied-row insertion leaves the complete visible response, canonical reads, query
embedding invocation count, and reranker inputs unchanged. A move after the first
canonical check removes the stale note and its link contribution before reranking.

## Deletion accounting

Across the three changed production files, physical lines decreased from 1,109 to
957: **152 net lines removed**. Removed concepts are the alternate retriever,
redundant evidence subclass/projection, import-time replacement, seven ambient
context variables, and wrapper-only setup/reset/cache methods. Essential metadata
selection, both canonical checks, link-support reauthorization, healthy identity
proof, runtime filtering, and disclosure logic remain explicitly owned by search.
No dependency or adjacent subsystem was added or redesigned.

## Documentation and discoverability review

Updated `docs/architecture.md` and
`docs/semantic-retrieval-conversation-architecture.md`. Reviewed
`docs/mcp-exploration-architecture.md`, the retrieval user manual, and
DD-014/060/061/062/066/087/089/090; documented public behavior remains unchanged.
No new user-facing capability, Explore entry, bridge method, MCP schema, CLI,
configuration, or setup behavior was introduced, so those surfaces require no edits.

## Validation results

- Baseline retrieval/context/conversation suites: 140 passed.
- Final retrieval/context/conversation suites: **146 passed** (61 retrieval,
  66 context, 19 conversation tests).
- Required conversation/facade/MCP/integration suites: **384 passed, 4 platform skips**.
- Full local pytest: **2,494 passed, 12 platform skips**, zero failures/errors
  across 2,506 collected tests. Skips require Linux `/proc/self/fd` or a
  case-sensitive filesystem.
- Repository-wide Ruff check and format check passed (539 files); mypy passed
  all 235 source files. Compileall, task workflow, manual links,
  documentation-impact evaluation, and diff whitespace checks passed.

Focused checks used the installed `.venv` tools. Required caller and full suites
used elevated `uv run` with fresh temporary directories outside `/private` and the
Git checkout, avoiding the previously verified macOS path/sandbox interference.
No unrelated source changes were needed for validation.

All six acceptance criteria and the local privacy/identity/relocation/determinism
review passed. No PR was opened or merged. Normal/security PR reviews and the
plugin/GitHub full-validation checkpoints remain required before any future merge.
No additional implementation follow-up was identified within this task's scope.
