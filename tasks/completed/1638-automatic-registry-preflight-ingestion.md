---
id: LIFEOS-1638
title: Add automatic registry preflight to ingestion workflows
status: completed
phase: 16
depends_on: []
risk: medium
---

# Goal

Remove manual registry refresh ceremony from normal MCP-driven ingestion while preserving
strict low-level source verification and the disposable-registry architecture.

When an external agent asks LifeOS to build an ingestion proposal from a canonical source,
LifeOS should first refresh authoritative derived registry state from the current vault. A
newly added or edited source should therefore be ingestible without a separate user-issued
`lifeos scan` or MCP `registry_refresh` call.

# Design principles

- Canonical Markdown remains authoritative; registry state is disposable and rebuildable.
- Refresh at the MCP/user-facing ingestion orchestration boundary, not inside low-level
  source-loading or proposal-building primitives.
- Reuse the authoritative `refresh_registry()` implementation; do not duplicate scan, hash,
  proposal-index, or file-tracking logic.
- Refresh failures fail closed before an ingestion draft is created.
- Preflight may mutate only derived registry/runtime diagnostics, never canonical Markdown.
- Proposal submit/approve/apply remain explicit and unchanged.

# Scope

- Add one shared MCP ingestion preflight that runs the authoritative full registry refresh
  immediately before proposal-building ingestion operations.
- Apply the preflight consistently to:
  - `ingestion_evolve_wiki_proposal`;
  - `study_evolve_learning_proposal`;
  - compatibility ingestion proposal tools that load a source and build wiki drafts.
- Preserve direct facade/ingestion behavior: low-level source verification remains
  refresh-free and continues to reject stale, unregistered, missing, or otherwise invalid
  source state.
- Record preflight refresh activity using existing disposable runtime activity conventions
  without exposing canonical note bodies.
- Add focused MCP tests for newly added and edited sources, study ingestion, compatibility
  tools, refresh failure, and strict low-level stale-source behavior where appropriate.
- Update user-facing ingestion workflow documentation so explicit scan/refresh is optional
  maintenance rather than a prerequisite for MCP proposal-building ingestion tools.

# Out of scope

- Incremental or source-only scanning optimization.
- Filesystem watchers or background refresh daemons.
- Changing canonical Markdown during preflight.
- Automatically submitting, approving, or applying proposals.
- Relaxing path/hash/ownership/provenance checks after refresh.
- Embedding an LLM or moving semantic reasoning into LifeOS.
- Changing explicit `lifeos scan` or `registry_refresh` maintenance commands.

# Acceptance criteria

- An MCP ingestion proposal can use a newly created canonical Markdown source without an
  explicit prior `registry_refresh` call.
- After a registered source is edited, MCP ingestion refreshes the registry and grounds the
  resulting draft in the new source content hash instead of failing with stale registry
  state.
- Study ingestion receives the same automatic preflight behavior.
- Compatibility ingestion proposal tools receive the same automatic preflight behavior.
- The shared preflight calls the existing authoritative full `refresh_registry()` contract
  rather than implementing a second scanner/indexer.
- If registry refresh fails, the ingestion tool fails before any proposal draft is created.
- Direct low-level source loading remains refresh-free and still fails closed on stale
  registry state.
- Preflight does not mutate canonical Markdown, generated ownership, or proposal lifecycle
  state beyond creating the requested draft after successful refresh.
- Runtime activity can distinguish the automatic refresh from the subsequent ingestion
  proposal action without storing canonical note bodies.
- User manual guidance no longer requires a manual refresh immediately before normal MCP
  ingestion, while explicit refresh remains documented as a supported maintenance tool.
- Normal CI and Docker clean-room setup/MCP gates remain green.

# Documentation impact

Status: required

- Updated `docs/user-manual/03-feature-breakdown.md`,
  `docs/user-manual/04-setup-and-installation.md`, and
  `docs/user-manual/05-workflow.md` so normal MCP ingestion documents automatic registry
  preflight and explicit scan/refresh remains a maintenance surface.
- Updated MCP server instructions and proposal-tool descriptions to advertise the same
  behavior to external agents.
- Architecture review resolved without a separate `docs/architecture.md` change: the
  implementation composes the existing MCP orchestration boundary with the existing
  authoritative registry-refresh contract and introduces no new canonical data,
  authorization boundary, ownership rule, mutation engine, or durable registry semantics.

# Validation

Final implementation validation on CI run `32669218955` before task closure:

- Documentation impact gate passed.
- Ruff passed.
- mypy passed with no issues in 184 source files.
- `compileall` passed.
- Manual links validated across 15 chapters.
- Test collection found 1535 tests.
- Full repository suite: `1535 passed in 47.37s`.
- Docker clean-room setup gate: `3 passed in 1.90s`.
- Docker MCP integration/lifecycle gate: `51 passed in 8.53s`.

The first CI pass exposed that the legacy MCP lifecycle integration fixture created a
hand-built vault without the Git repository guaranteed by first-party `lifeos init`.
Automatic authoritative refresh correctly exercised that missing bootstrap condition.
The fixture was aligned with the supported Git-backed vault contract; production refresh
behavior was not weakened and continues to fail closed on refresh errors.

# Completion evidence

- All five MCP proposal-building ingestion entrypoints invoke one shared automatic
  full-registry preflight immediately before proposal facade/source verification.
- New and edited sources are grounded in the latest content hash without a separate manual
  `lifeos scan` or `registry_refresh` step.
- Study ingestion and compatibility ingestion tools use the same preflight.
- Refresh failure stops before proposal creation.
- Direct low-level ingestion/source verification remains refresh-free and strict.
- Preflight activity is separately inspectable as `ingestion_registry_preflight` without
  canonical note bodies.
- Explicit `lifeos scan` and MCP `registry_refresh` remain available for maintenance and
  diagnostics.

# Relevant decisions

- DD-033: SQLite/runtime registry state is disposable and rebuildable from canonical vault
  files.
- DD-035: generated ownership remains canonical authorization data and is not repaired or
  rewritten by registry preflight.
- DD-036: Python remains the sole business-rule engine.
- DD-087: clean-room setup/MCP validation remains deterministic infrastructure testing.
- DD-088: first-party bootstrap and runtime tooling must not mutate external client config.
