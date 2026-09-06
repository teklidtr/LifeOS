---
id: LIFEOS-1737
title: Expose composable generic agent workflows through MCP
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1735
  - LIFEOS-1736
risk: high
---

# Goal

Expose the generic source and reviewed-change facade operations through the LifeOS MCP adapter so an
external agent can satisfy novel user requests by composing a small safe capability set instead of
requiring a new MCP function for every semantic intent.

The agent should understand requests such as adding a résumé, preserving a property document,
using salary history as career context, or importing an arbitrary file without LifeOS implementing
`resume_import`, `property_import`, `salary_import`, or comparable intent-specific tools.

# Scope

- Expose strict MCP adapters over the LIFEOS-1735 generic facade operations, with public tool names
  equivalent to:
  - `source_import`;
  - `source_inspect`;
  - `source_extract`.
- Expose a strict MCP adapter over LIFEOS-1736 `change.propose`, with a generic public tool name such
  as `change_propose`.
- Keep MCP as an adapter over the typed facade. Do not reproduce hashing, attachment storage,
  extraction, privacy, ownership, proposal construction, stale-write, or application logic in MCP.
- Preserve the existing proposal lifecycle tools. Generic proposal creation stops at draft; submit,
  approve, and apply remain separate explicit user-authorized transitions.
- Update the Python-owned MCP runtime instructions/agent operating contract so external agents are
  taught to:
  - infer the user's semantic intent themselves;
  - explore/read relevant vault context before durable semantic changes when context matters;
  - use generic source import and ordinary-change proposal primitives for novel ordinary intents;
  - use specialized LifeOS tools when a domain has a real schema, state machine, lifecycle, or
    safety invariant;
  - treat zero durable changes as a valid result;
  - never bypass source-import storage, proposal, ownership, privacy, or stale-write boundaries by
    manually editing implementation-owned paths;
  - never add or expect a new MCP operation merely because a new user intent or file label appears.
- Keep implementation invariants in deterministic LifeOS code rather than model instructions. The
  agent may know that imports must go through LifeOS and consequential semantic changes must go
  through proposals; it must not be responsible for calculating storage hashes, review digests,
  patch hashes, or ownership state.
- Preserve transport narrowing:
  - local vault-scoped STDIO may expose explicitly requested import from a regular file path that is
    visible to the same local LifeOS process and passes the facade ingress checks;
  - authenticated home-node/network transport must not turn `source_import` into arbitrary remote
    reading of server filesystem paths. Until LifeOS has a separate safe upload/handle protocol,
    omit or explicitly mark path-based source import unavailable on that transport;
  - canonical-source inspection/extraction exposed remotely must still obey the existing retrieval
    and protected-scope policy before source content or extracted text is disclosed.
- Add deterministic integration/contract tests proving that the same generic tool inventory can
  support multiple distinct workflows without intent-specific production APIs.
- Preserve existing specialized MCP operations. This task is not a wholesale conversion of every
  domain workflow into generic tools.

# Out of scope

- Building an embedded autonomous agent or natural-language intent classifier inside LifeOS.
- Resume-, finance-, property-, tax-, medical-, or other domain-specific MCP functions.
- A remote binary upload protocol, browser upload UI, or arbitrary home-node filesystem access.
- Removing specialized MCP tools whose domain semantics justify them.
- Automatic submit/approve/apply after `change_propose`.
- Making the agent responsible for hashes, manifests, ownership, proposal-document bytes, review
  digests, locks, or recovery internals.
- Reintroducing repository prompt files or provider-specific agent runtimes.

# Required invariants

- MCP remains transport/adaptation; the typed facade and domain services remain authoritative for
  LifeOS behavior.
- New ordinary user intent is handled by agent reasoning and composition, not by adding a bespoke
  MCP function.
- A specialized tool is justified by distinct deterministic LifeOS semantics or invariants, not by
  a noun in the user's request.
- The local path import surface cannot expand the home-node trust boundary into arbitrary server
  filesystem reads.
- Protected source content cannot influence or cross an external MCP boundary until existing policy
  and explicit protected-scope intent allow it.
- Generic change proposals stop at draft and cannot bypass specialized domain mutation workflows.
- Zero-change and preserve-only flows remain first-class outcomes.

# Acceptance criteria

- Local STDIO MCP exposes generic source import/inspect/extract and generic reviewed-change proposal
  tools backed by the existing typed facade.
- The authenticated home-node/network MCP surface does not accept arbitrary host file paths for
  `source_import`; capability advertisement and failure behavior accurately reflect the narrowed
  transport.
- MCP schemas are strict, bounded, provider-neutral, and do not expose implementation-owned hash,
  manifest-layout, proposal-byte, ownership, or storage-path fields as caller responsibilities.
- Runtime agent instructions clearly state the composition rule: do not create/use a new MCP
  operation merely for a new ordinary user intent when existing generic operations suffice.
- Runtime instructions also state the complementary rule: use specialized operations when LifeOS
  owns distinct schema/lifecycle/safety semantics, and never use generic change proposals to bypass
  them.
- A deterministic end-to-end fixture can represent a résumé-like PDF flow using only generic tools:
  import -> local extraction/inspection -> relevant vault exploration -> draft creation for an
  eligible `profile/` note. No production identifier or branch contains `resume_import` or an
  equivalent résumé-specific API.
- A second semantically different fixture, such as TSV/XML personal history, uses the same generic
  source tools and can ground a different eligible ordinary-note proposal without new MCP methods.
- A preserve-only fixture imports a source and intentionally creates no semantic proposal.
- A protected-source fixture proves that source content/extracted text is not disclosed to an
  external caller without the existing two-key protected-scope authorization.
- A specialized-domain fixture proves that `change_propose` cannot mutate a lifecycle/schema-owned
  artifact and that the appropriate specialized capability remains the valid path.
- Existing MCP exploration, ingestion, proposal lifecycle, Rich Capture, bridge, privacy, and
  integration regression suites continue to pass.

# Documentation impact

Status: required

- `AGENTS.md`: add the durable development rule that new ordinary user intents should compose
  existing generic facade/MCP capabilities; add specialized operations only for genuinely distinct
  deterministic semantics or invariants.
- `docs/architecture.md`: document MCP as the adapter over the composable generic facade surface and
  document local-vs-network source-ingress narrowing.
- `docs/mcp-exploration-architecture.md`: document the generic source/change tool composition model,
  privacy boundary, and transport availability.
- `docs/user-manual/15-mcp-exploration.md`: document how an agent can import a generic personal file,
  inspect/extract it, reason over vault context, propose ordinary durable context, or stop after
  preservation without file-type-specific LifeOS features.
- `docs/user-manual/03-feature-breakdown.md`: reflect the user-facing generic source-import ability
  and its relationship to Rich Capture and agent-assisted workflows.

# Capability discoverability impact

Status: required

- Registry: add or update a semantic capability for generic source/file import backed by the new MCP
  tools and existing Rich Capture storage/extraction behavior. Keep low-level generic change
  proposal mechanics grouped as internal infrastructure unless they are already owned by a broader
  user-facing capability.
- Explore: `explore` for the user-facing ability to add arbitrary personal files/sources to LifeOS
  and optionally let an agent integrate useful durable context. Teaching prompts should include both
  an integrate-if-useful example and a preserve-only example so the capability does not imply that
  every import must produce semantic changes.

# Validation commands

```bash
uv run pytest -q tests/facade tests/captures tests/mcp
uv run pytest -q tests/integration tests/bridge
uv run pytest -q
uv run ruff check .
uv run mypy src
python scripts/validate_tasks.py
python scripts/validate_manual_links.py
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
```

Because this task changes externally callable MCP surfaces, protected-scope behavior, file ingress,
and canonical proposal routing, treat it as security-sensitive under `AGENTS.md`: perform the
pre-review invariant audit, broad local regression validation, normal Codex review when stable, and
security review after the normal review cycle stabilizes.

# Relevant design decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-003: Durable proposal mode.
- DD-004: Proposal application is explicit.
- DD-017: Original sources remain immutable.
- DD-036: Python is the sole business-rule engine.
- DD-037: default desktop transport is vault-scoped STDIO.
- DD-062: protected external disclosure requires policy permission and explicit request intent.
- DD-074 through DD-078: Rich Capture storage, processing, privacy, and recovery contracts.
- DD-079: agent-assisted ingestion is MCP-only; the external agent decides semantic meaning while
  LifeOS owns deterministic validation and proposal safety.
- LIFEOS-113: provider-independent typed facade for approved agent/adapter operations.
- LIFEOS-1639: external-agent exploration and controlled mutation remain bounded by privacy,
  proposal, provenance, and authorization semantics.
- MCP Exploration Architecture.
