---
id: LIFEOS-1726
title: Integrate privacy and identity coherence into the hybrid retriever
status: backlog
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

- [ ] All public retriever entry points reach one static implementation; the coherence subclass and redundant evidence wrapper are removed or reduced to ordinary compatibility aliases with no behavior.
- [ ] One visible authorization flow enforces policy before every relevant influence boundary without leaving the old path reachable through direct imports.
- [ ] Existing privacy-before-influence, runtime-query, stable-identity exposure, ranking, provider, relocation, and context-consumer tests retain equivalent behavior coverage.
- [ ] Verify that denied content cannot alter visible ranking/corpus statistics or trigger provider reads, including alternate candidate paths. Preserve existing adversarial tests and add only material missing coverage exposed by the migration.
- [ ] Audit all renamed helpers, imported classes, constructor/return shapes, accessed attributes, patch points, and exact error strings; preserve compatibility or migrate justified private seams completely.
- [ ] Record removed concepts and conservative net production change. Essential privacy and verified-identity logic remains explicitly owned and reviewable.

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
