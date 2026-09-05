---
id: LIFEOS-1723
title: Consolidate MCP input construction and equivalent read output contracts
status: backlog
phase: hardening
depends_on: []
risk: high
---

# Goal

Use the existing FastMCP/Pydantic boundary to eliminate duplicated input-model construction and genuinely redundant read-output representations, while preserving all intentional MCP contracts.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, input-model construction is repeated in `mcp.server._strict_tool`, `mcp.exploration_tools._strict_tool`, and `mcp.multi_source_tools._proposal_tool`. They do not all use the same strictness. Read tools also project facade dataclasses into dictionaries annotated with mirrors in `src/lifeos/mcp/models.py`: `VaultPathEntryMCPResult`, `VaultListMCPResult`, `VaultReadItemMCPResult`, `VaultReadManyMCPResult`, `WikiSearchHitMCPResult`, and `WikiSearchMCPResult`.

The representative chains are `facade.exploration` list/read-many result dataclasses and `facade.read_only` wiki-search result dataclasses, through registered functions in `mcp/exploration_tools.py` and `mcp/server.py`, to SDK-generated output models. Direct `tool.fn()` callers are part of the compatibility inventory. Revalidate the exact dependency lock and implementation HEAD before choosing the adapter.

# Scope

- Consolidate the three input-model construction implementations into one small MCP-owned mechanism while preserving each tool family's strictness, extra-field behavior, aliases, descriptions, annotations, defaults, and parameter schema.
- Deeply characterize list-vault output first, including its nested entries, then migrate read-many and wiki search where the same contract-preserving approach fits.
- Remove the six named output mirrors and their handwritten projections where redundant. Derive validation/serialization from authoritative facade types through the existing optional MCP dependency boundary.
- Verify the currently locked FastMCP v1 and Pydantic behavior with Context7 and authoritative SDK documentation/source. Do not assume a frozen/slotted dataclass annotation automatically produces structured output or validates an existing instance.
- Establish the minimal reusable output boundary for LIFEOS-1724 with valid output, invalid nested output, and wire-schema evidence. Do not introduce Pydantic into otherwise dependency-free domain code just to expose MCP results.

# Out of scope

- Proposal/research output adoption (LIFEOS-1724), a new validation dependency, SDK major-version migration, or a generic schema framework.
- Removing intentional DTOs for disclosure/projection/default differences: registry-refresh optional rename reporting, vault-context ranking/provenance mapping, note-identity field selection/renaming, read-markdown requiredness, runtime-activity optional fields, and research-query aggregation.
- Opportunistically narrowing vault-search/link diagnostic schemas from unrestricted strings to domain enums. Investigate separately only if required for the named read families.

# Required invariants

- Preserve published input/output schemas, including requiredness, constraints, aliases, descriptions, defaults, optional-key omission, and nested references/titles where contractually observable. Do not silently accept schema churn as a cosmetic change.
- Preserve structured and text output shape/content, strict bool/int behavior, unknown-field handling, null/empty distinctions, tool annotations, error classes/messages/disclosure, and validation timing.
- Existing malformed domain instances, including invalid nested literals, must still be rejected as invalid output. A serializer that trusts previously constructed dataclasses is insufficient.
- Preserve direct `tool.fn()` call/return compatibility wherever used or required; returning a model in place of a dictionary is not automatically compatible. Inventory and justify any internal-only seam migration, with every caller/test updated in the same change.
- Preserve policy-before-read/disclosure and trusted runtime/actor authority. Input refactoring must not make those values client-controlled or expose rejected input values in errors.

# Acceptance criteria

- [ ] All three input construction sites use one implementation with their original per-family behavior.
- [ ] A family-by-family contract comparison identifies redundant and necessary representations. The named read families use authoritative types where compatible; any retained mirror has a concrete schema/validation/direct-call reason.
- [ ] At least one complete redundant output representation chain disappears, and the supported pattern works across compatible named families without handwritten duplicate field lists.
- [ ] Wire and direct-call tests cover successful results, malformed nested output, strict/extra-field inputs, aliases/defaults, annotations, and sanitized errors. Existing behavioral/privacy tests remain.
- [ ] Net production/symbol deletion is recorded after accounting for the output boundary and compatibility adapters; no large translation or schema-mutation layer is introduced merely to claim mirror deletion.
- [ ] If a particular family cannot preserve its contract with the narrow boundary, retain that DTO and document the limitation; do not widen scope into a transport/domain rewrite or weaken validation.

# Documentation impact

Status: required
- `docs/mcp-exploration-architecture.md`: document input construction ownership, the authoritative-type output boundary, and retained transport-specific DTOs.
- `docs/architecture.md`: align MCP adapter ownership if needed.
- Review `docs/user-manual/15-mcp-exploration.md` for compatibility; this task does not change tool behavior or advertise new capabilities.

# Validation

```bash
uv run pytest -q tests/mcp tests/facade tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Run with the optional MCP SDK installed so schema, structured-output, and real STDIO client tests execute rather than skip. Compare generated contracts before/after; do not bless changed snapshots without assessing the actual contract. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-062, DD-079, DD-087, and DD-091: protected retrieval, MCP ingestion/runtime ownership, and shared authenticated transport.
- SDK capability reference to reverify against the lock: [Python SDK v1 structured output](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/docs/server.md#structured-output).

# Implementation size and sequencing

Medium. Independent foundation for LIFEOS-1724. Owns all three input-model constructors and only the named read outputs; the next task consumes this boundary rather than rebuilding it.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** SDK schema generation, instance revalidation, strictness, and direct-call compatibility require careful semantic comparison, but the work stays inside one transport adapter. Sol with high reasoning fits this boundary-design task without requiring Astra.
