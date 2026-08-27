---
id: LIFEOS-1642
title: Converge Context Packs with hybrid semantic retrieval
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1639
risk: medium
---

# Goal

Evolve the existing `ContextPack` / `vault_context` capability from its original lexical-only
source selection into a stable agent context-management surface backed by LifeOS's already
implemented hybrid retrieval subsystem, without changing the responsibility boundary between
LifeOS retrieval and external-agent reasoning.

The external agent should continue to ask for a bounded context pack and then decide what to
read, search, compare, or investigate next. LifeOS may improve the quality of the initial map
through lexical, semantic, metadata, links, graph hints, explicit focus paths, and applicable
instructions without turning context selection into a hidden agent brain.

# Design principles

- Context Packs are bounded context management, not a replacement for agent-led exploration.
- Reuse `src/lifeos/retrieval` and LIFEOS-1400..1411; do not build a second vector/RAG stack.
- Preserve a stable, simple agent-facing `vault_context` contract wherever practical while
  allowing the retrieval implementation behind it to improve.
- Explicit focus paths are authoritative context requests and must not disappear merely
  because semantic ranking scores other notes more highly.
- Applicable `system/instructions.yml` rules remain a separate policy/context signal, not
  vector-search content or mutation permission.
- Retrieval state remains derived, disposable, privacy-scoped, explainable, and safely
  degradable.
- Semantic/vector retrieval improves the agent's senses; the external agent still decides
  what matters and what to inspect next.

# Scope

- Audit the current lexical `build_context_pack()` / `vault_context` implementation against
  the completed provider-neutral hybrid retrieval subsystem from LIFEOS-1400..1411.
- Replace or compose the lexical-only candidate-selection path with the authoritative hybrid
  retrieval service where available, while preserving existing Context Pack semantics for:
  - `question`;
  - explicit `focus_paths`;
  - applicable typed instructions;
  - bounded source count/context budget;
  - source identity and inspectable excerpts;
  - evidence gaps;
  - omissions;
  - diagnostics.
- Reuse the existing hybrid retrieval signals rather than rebuilding them in the context
  package:
  - exact/lexical matching;
  - semantic/vector similarity when configured and healthy;
  - metadata;
  - links and graph hints;
  - deduplication and deterministic ordering;
  - privacy/protected-scope filtering;
  - degraded/no-provider behavior.
- Preserve lexical/local fallback when semantic providers, embeddings, or indexes are absent,
  stale, unhealthy, or intentionally disabled. `vault_context` must remain useful without an
  embedding provider.
- Keep explicit focus paths in the final Context Pack before filling the remaining budget with
  retrieved candidates. Focus paths must still pass normal vault safety/privacy validation.
- Define deterministic merging/deduplication when a focus path is also returned by hybrid
  retrieval.
- Preserve or extend inspectability so an agent/user can tell why a source entered the pack
  without exposing hidden model reasoning. Where existing retrieval explanations are
  available, surface bounded machine-readable retrieval reason/mode metadata in a backwards-
  compatible way.
- Ensure instruction applicability is evaluated against the final selected context sources,
  not against an unrelated pre-retrieval candidate set.
- Improve evidence-gap/omission reporting so degraded semantic retrieval, limited budgets,
  protected exclusions, and sparse evidence are distinguishable rather than silently treated
  as equivalent.
- Review whether `wiki_search` should delegate to the same retrieval service or remain a
  deliberately lexical primitive. Preserve a distinct exact/lexical capability if agents need
  it; do not remove useful composability merely to unify implementations.
- Expose the richer Context Pack through MCP using the same `vault_context` tool name/request
  shape where compatibility allows, so agents benefit from improved retrieval without needing
  provider-specific knowledge.
- Coordinate with LIFEOS-1639 so agents still have separate composable list/read/search/link
  operations after receiving an initial Context Pack; `vault_context` must not become a giant
  one-shot `ingest()` or answer-generation tool.
- Add deterministic tests comparing lexical-only fallback, hybrid retrieval, explicit focus,
  privacy exclusion, stale/degraded index, deduplication, budget, and instruction-routing
  behavior.

# Out of scope

- Implementing embeddings, vector storage, hybrid retrieval, or knowledge conversations from
  scratch; those capabilities already exist in LIFEOS-1400..1411.
- Embedding an LLM/provider runtime inside LifeOS.
- Having LifeOS automatically perform iterative semantic reasoning or decide which durable
  wiki changes should be made.
- Persisting ordinary Context Packs as canonical Markdown.
- Removing lexical search as an explicit useful exploration primitive.
- Allowing semantic similarity to override protected-scope exclusions or instruction policy.
- Building the external research/raw-ingestion query loop; that is LIFEOS-1641.
- Building remote/home-node transport; that is LIFEOS-1640.

# Acceptance criteria

- `vault_context(question, focus_paths, limit)` continues to provide a bounded Context Pack
  through MCP without requiring the agent to know which embedding/vector provider is in use.
- When the existing hybrid retrieval subsystem is configured and healthy, Context Pack source
  selection composes its lexical, semantic, metadata, link, and graph signals instead of using
  the old standalone lexical-only ranking path.
- When semantic retrieval is unavailable or degraded, Context Packs safely fall back to local
  deterministic retrieval and report the degraded/omitted capability rather than failing the
  whole query unnecessarily.
- Explicit focus paths remain present, validated, deduplicated, and budgeted predictably.
- Applicable instructions are computed for the final Context Pack and remain distinct from
  retrieval ranking and mutation authority.
- Protected scopes are excluded before candidate exposure/provider disclosure according to
  existing retrieval privacy contracts.
- Sources retain inspectable paths/excerpts and bounded retrieval explanation metadata; no
  hidden chain-of-thought is stored or returned.
- Evidence-gap and omission output distinguishes sparse evidence, result-budget truncation,
  protected exclusions, and unavailable/degraded semantic retrieval where relevant.
- The implementation reuses the completed retrieval/index/provider services and does not
  create a second embedding index or vector-store abstraction.
- MCP callers receive the richer behavior without a provider-specific tool contract or a
  mandatory API change.
- Agent-led iterative exploration remains possible through LIFEOS-1639 read/discovery tools;
  Context Packs provide a starting map rather than a deterministic final crawl.
- Existing Context Pack, retrieval, MCP, privacy, and integration tests remain green with new
  convergence coverage added.

# Documentation impact

Status: required

- `docs/architecture.md`: document Context Packs as the bounded context-management layer over
  the authoritative hybrid retrieval subsystem and preserve the agent/retrieval boundary.
- Retrieval/knowledge-conversation architecture docs: clarify how Context Packs reuse existing
  hybrid retrieval, privacy, fallback, and explanation contracts.
- `docs/user-manual/03-feature-breakdown.md`: explain that `vault_context` may use hybrid
  retrieval while remaining useful in lexical/local fallback mode.
- `docs/user-manual/05-workflow.md`: document Context Pack as an initial bounded context map
  followed by optional iterative agent exploration.
- MCP documentation/tool descriptions must remain synchronized with the finalized behavior.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/context tests/retrieval tests/conversations tests/mcp tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- LIFEOS-300: Context Packs began as deterministic lexical routing with inspectable evidence,
  omissions, and gaps; embeddings were intentionally out of scope at that stage.
- LIFEOS-1400 through LIFEOS-1411: provider-neutral semantic/hybrid retrieval, chunking,
  indexes, conversations, citations, bridge exposure, privacy, and recovery already exist and
  are the authoritative subsystem to compose.
- LIFEOS-1639: MCP exploration must remain broad/composable while mutation stays constrained.
- LIFEOS-1641: external-research query pipelines may consume Context Packs but own a separate
  evidence-acquisition/ingestion concern.
- DD-036: Python remains the sole business-rule engine.
- DD-060: semantic similarity is an optional signal layered beside exact lexical matching,
  metadata, links, and graph candidates.
- DD-061: chunks, embeddings, ranking state, and rebuild journals remain disposable.
- DD-062: protected retrieval scopes default deny before candidate generation/provider use.
- DD-063 through DD-066: conversation artifacts, citation validation, proposal outcomes, and
  provider neutrality remain authoritative.
