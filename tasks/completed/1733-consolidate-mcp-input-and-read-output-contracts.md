---
id: LIFEOS-1733
title: Consolidate MCP input construction and equivalent read output contracts
status: completed
phase: hardening
depends_on: []
risk: high
---

# Goal

Use the existing FastMCP/Pydantic boundary to eliminate duplicated input-model construction and genuinely redundant read-output representations, while preserving all intentional MCP contracts.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, input-model construction was repeated in `mcp.server._strict_tool`, `mcp.exploration_tools._strict_tool`, and `mcp.multi_source_tools._proposal_tool`. They did not all use the same strictness. Read tools also projected facade dataclasses into dictionaries annotated with mirrors in `src/lifeos/mcp/models.py`: `VaultPathEntryMCPResult`, `VaultListMCPResult`, `VaultReadItemMCPResult`, `VaultReadManyMCPResult`, `WikiSearchHitMCPResult`, and `WikiSearchMCPResult`.

The representative chains are `facade.exploration` list/read-many result dataclasses and `facade.read_only` wiki-search result dataclasses, through registered functions in `mcp/exploration_tools.py` and `mcp/server.py`, to SDK-generated output models. Direct `tool.fn()` callers are part of the compatibility inventory.

# Scope

- Consolidate the three input-model construction implementations into one small MCP-owned mechanism while preserving each tool family's strictness, extra-field behavior, aliases, descriptions, annotations, defaults, and parameter schema.
- Deeply characterize list-vault output first, including its nested entries, then migrate read-many and wiki search where the same contract-preserving approach fits.
- Remove the six named output mirrors and their handwritten projections where redundant. Derive validation/serialization from authoritative facade types through the existing optional MCP dependency boundary.
- Verify the currently locked FastMCP v1 and Pydantic behavior with Context7 and authoritative SDK documentation/source. Do not assume a frozen/slotted dataclass annotation automatically produces structured output or validates an existing instance.
- Establish the minimal reusable output boundary for LIFEOS-1724 with valid output, invalid nested output, and wire-schema evidence. Do not introduce Pydantic into otherwise dependency-free domain code just to expose MCP results.

# Out of scope

- Proposal/research output adoption (LIFEOS-1724), a new validation dependency, SDK major-version migration, or a generic schema framework.
- Removing intentional DTOs for disclosure/projection/default differences: registry-refresh optional rename reporting, vault-context ranking/provenance mapping, note-identity field selection/renaming, read-markdown requiredness, runtime-activity optional fields, and research-query aggregation.
- Opportunistically narrowing vault-search/link diagnostic schemas from unrestricted strings to domain enums.

# Required invariants

- Preserve published input/output schemas, including requiredness, constraints, aliases, descriptions, defaults, optional-key omission, and nested references/titles where contractually observable.
- Preserve structured and text output shape/content, strict bool/int behavior, unknown-field handling, null/empty distinctions, tool annotations, error classes/messages/disclosure, and validation timing.
- Existing malformed domain instances, including invalid nested literals and coercible scalar values, must be rejected as invalid output.
- Preserve direct `tool.fn()` call/return compatibility wherever used or required; returning a model in place of a dictionary is not automatically compatible.
- Preserve policy-before-read/disclosure and trusted runtime/actor authority. Input refactoring must not make those values client-controlled or expose rejected input values in errors.

# Acceptance criteria

- [x] All three input construction sites use one implementation with their original per-family behavior.
- [x] A family-by-family contract comparison identifies redundant and necessary representations. The named read families use authoritative types where compatible; retained mirrors have concrete schema/validation/direct-call reasons.
- [x] The six named redundant output mirrors and their handwritten projections are removed, and the supported pattern works across list, read-many, and wiki-search without duplicate field lists.
- [x] Wire and direct-call tests cover successful results, malformed nested output, strict/coercible-invalid scalar output, strict/extra-field inputs, aliases/defaults, annotations, and sanitized errors. Existing behavioral/privacy tests remain.
- [x] Net production/symbol deletion is recorded after accounting for the output boundary and compatibility adapters; no large translation or schema-mutation layer was introduced merely to claim mirror deletion.
- [x] Intentional transport DTOs with disclosure, requiredness, omission, selection, or aggregation differences remain explicit rather than being forced through the authoritative-dataclass shortcut.

# Documentation impact

Status: required

- Updated `docs/mcp-exploration-architecture.md` to document shared input construction ownership, the authoritative-dataclass output boundary, retained transport-specific DTOs, and deterministic contract tests.
- Reviewed `docs/architecture.md`; no additional ownership change was needed because the existing architecture already places transport adaptation inside the MCP layer.
- Reviewed `docs/user-manual/15-mcp-exploration.md`; no user-manual edit was required because tool names, inputs, outputs, errors, privacy behavior, and capabilities remain unchanged.

# Implementation evidence

- Added `lifeos.mcp.tool_contracts.build_mcp_tool` as the single FastMCP argument-model construction seam used by core, exploration, and multi-source tool families. Core tools retain normal Pydantic coercion plus unknown-field rejection; exploration and multi-source tools retain strict type validation plus unknown-field rejection.
- Added a narrow authoritative-output adapter that recursively derives Pydantic models from facade dataclasses while preserving historical `*MCPResult` titles and nested `$defs` references. Authoritative dataclass instances are validated with `model_validate(..., strict=True)` before JSON serialization, so malformed nested or coercible scalar values cannot be normalized into valid-looking output. The generated model itself remains JSON-compatible for FastMCP's second wire-validation pass, which receives lists after tuple fields are serialized.
- `VaultListResult`, `VaultReadManyResult`, and `WikiSearchResult` now own the compatible field lists. Direct `tool.fn()` callers still receive dictionaries, while FastMCP continues to expose identical text and structured content.
- Removed `VaultPathEntryMCPResult`, `VaultListMCPResult`, `VaultReadItemMCPResult`, `VaultReadManyMCPResult`, `WikiSearchHitMCPResult`, and `WikiSearchMCPResult` from `mcp/models.py`.
- Retained MCP DTOs where transport semantics intentionally differ from one authoritative facade result, including registry-refresh omission behavior, vault-context projection, note identity selection/renaming, read-markdown requiredness, runtime activity optional fields, and research aggregation.
- Added focused contract regressions for input strictness/coercion, aliases/defaults/annotations, legacy schema titles/references, direct dictionary returns, structured wire content, malformed nested literals, coercible malformed bool/int values, and sanitized runtime errors. The STDIO suite also exercises structured `wiki_search` output through a real MCP client.

## Deletion and size accounting

Against task base `b9594dcb0319d76cd99670f2513382a8fcd0a5ed`, the completed production `src/` diff is **166 additions and 176 deletions, net -10 lines**. The textual reduction is modest because the new shared adapter and regression-safe compatibility plumbing replace duplicated local implementations, but the conceptual deletion is larger:

1. three separate FastMCP input-model construction bodies collapse onto one MCP-owned implementation;
2. six redundant output mirror symbols disappear completely;
3. three handwritten list/read-many/wiki-search field projections no longer duplicate authoritative facade result field lists.

The added boundary remains narrow: it handles FastMCP argument policy, recursive compatible-dataclass output validation/model generation, and JSON mapping serialization only. It does not become a generic schema framework or move Pydantic into facade/domain contracts.

# Validation

The execution environment could not clone the repository locally because DNS resolution for `github.com` was unavailable, so repository validation used clean GitHub-hosted Actions checkouts with the locked dependency set and optional MCP SDK installed.

Before Codex review, full-validation run `34033297974` completed all four pytest shards successfully; the `full-test` aggregator passed, as did the clean-room setup/MCP gate and home-node service-container gate. The same implementation line had already passed Ruff, mypy, compile, test collection, project contract smoke tests, documentation impact, task workflow, manual links, and Obsidian plugin lint/typecheck/test/build.

Codex review then identified one P2 output-validation gap. After adding strict authoritative validation and coercible-scalar regressions, PR-check run `34033989260` passed Ruff, mypy, compile, collection, contract smoke tests, task/docs gates, and Obsidian validation.

The first post-review full-validation run `34034138282` exposed an interaction that the fast smoke set did not cover: placing `strict=True` on the generated model configuration made FastMCP's second validation pass reject the already-serialized JSON list for an authoritative tuple field. The failure appeared consistently in the direct/wire contract test, STDIO protocol test, remote home-node MCP test, and clean-room MCP gate. The boundary was corrected so strictness is applied only while validating the authoritative dataclass instance; FastMCP's wire revalidation can then accept the JSON list representation while scalar coercion remains impossible before serialization.

Repository-wide `uv run ruff format --check .` remains a pre-existing repository baseline blocker tracked by LIFEOS-1734. This task did not widen into the unrelated repository-wide formatter migration.

A fresh full-validation run on the corrected final completed-task head is required by root `AGENTS.md` before merge.

# Codex review

Normal Codex review of head `378b38540cdf4e8da20a64a9e65500ca84990355` found one P2 issue: authoritative output validation used normal Pydantic coercion, so values such as `truncated="false"`, numeric strings, or `True` in an integer field could be silently converted instead of exposing an upstream contract violation.

The finding is addressed by call-time strict validation of the authoritative dataclass plus regressions for coercible malformed boolean/integer values. A full-validation follow-up then refined the implementation so that strict source validation is not accidentally reused as strict validation of the JSON-normalized wire dictionary. The original review thread was replied to with the fix evidence and resolved. Security review was intentionally skipped per the user's explicit instruction for this task.

# Relevant design decisions

- DD-062, DD-079, DD-087, and DD-091: protected retrieval, MCP ingestion/runtime ownership, and shared authenticated transport.
- SDK capability reference verified against the locked stack: Python SDK v1 structured output behavior and Pydantic 2.13.4 attribute-based validation/schema generation.

# Implementation size and sequencing

Medium. Independent foundation for LIFEOS-1724. Owns all three input-model constructors and only the named compatible read outputs; LIFEOS-1724 can consume this boundary rather than rebuilding it.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** SDK schema generation, instance revalidation, strictness, and direct-call compatibility require careful semantic comparison, but the work stays inside one transport adapter.
