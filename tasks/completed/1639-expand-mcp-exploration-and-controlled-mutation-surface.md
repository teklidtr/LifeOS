---
id: LIFEOS-1639
title: Expand MCP exploration and controlled mutation surface
status: completed
phase: 16
depends_on: []
risk: medium
---

# Goal

Make the LifeOS MCP surface rich enough that an external agent can explore, crawl, search,
read, compare, and reason over a vault without requiring direct filesystem or shell access,
while keeping all canonical mutations behind LifeOS authorization, proposal, provenance,
ownership, and lifecycle rules.

The durable design principle is:

> LifeOS should constrain mutation, not exploration.

Agent intelligence must remain responsible for deciding what is relevant, what to inspect
next, what concepts connect, and what durable changes are worth proposing. LifeOS should
provide safe, composable senses and guarded hands rather than turning ingestion into a
single deterministic black box.

# Design principles

- Read/exploration surfaces should be broad, composable, typed, bounded, and safe.
- Write/mutation surfaces should remain narrow, intentional, authorized, and reviewable.
- Agent semantic reasoning remains external; LifeOS does not embed an LLM/provider runtime.
- Remote and local agents should receive equivalent LifeOS capabilities through the same
  authoritative Python business rules.
- Prefer LifeOS-native read primitives over granting agents arbitrary shell/filesystem
  access to the vault.
- Read/discovery correctness must use portable Python/LifeOS filesystem abstractions rather
  than depend on GNU/Linux versus BSD/macOS command-line utility behavior.
- Reuse existing secure traversal, privacy scopes, retrieval, proposal, ownership, and
  provenance contracts rather than duplicating them in MCP-specific code.

# Scope

- Audit the current MCP tool surface against the exploratory operations an agent normally
  performs with filesystem tools such as `find`, `grep`, and `cat`.
- Define and implement the missing composable read-only MCP operations needed for an agent
  to iteratively navigate the vault. The final surface should cover, directly or through
  existing tools:
  - bounded path/folder discovery within allowed vault scopes;
  - safe Markdown reads;
  - text and semantic search where supported;
  - metadata/context inspection;
  - link/reference/backlink discovery where available from authoritative LifeOS indexes;
  - bounded multi-read/comparison workflows when they materially reduce tool-call overhead.
- Implement filesystem-facing exploration primitives with portable Python 3.11+/LifeOS
  abstractions such as `pathlib` and existing secure I/O helpers. Do not rely on subprocess
  invocation of GNU/BSD `find`, `grep`, `sed`, `cat`, or platform-specific shell behavior for
  the authoritative operation semantics.
- Preserve iterative agent-led exploration. A client must be able to search, inspect one or
  more results, refine the search, follow references, and continue reasoning without a
  local vault copy.
- Audit all MCP mutation tools and make the read/write boundary explicit in naming,
  descriptions, safety metadata, DTOs, and tests.
- Keep canonical wiki/study/goal/plan/etc. writes behind existing proposal and consequential
  tool contracts. Do not expose a generic arbitrary `write_file`, `delete_file`, `move`, or
  shell-equivalent mutation surface for canonical vault data.
- Ensure traversal protection, privacy/routing policy, result bounds, actor identity, and
  error behavior remain deterministic and enforced by LifeOS core/facades rather than by
  prompt instructions alone.
- Add MCP integration tests demonstrating a realistic multi-step exploratory crawl and a
  separate mutation attempt that cannot bypass proposal/authorization rules.
- Update MCP/user/architecture documentation with the exploration-versus-mutation contract.

# Out of scope

- Running LifeOS as a network-accessible daemon or home node; that is LIFEOS-1640.
- Adding a second LLM runtime, model provider, embeddings provider, or agent loop inside
  LifeOS.
- Giving external agents unrestricted shell access to the LifeOS host.
- Replacing the proposal engine, generated ownership model, provenance model, or existing
  consequential-tool authorization semantics.
- Making semantic ingestion deterministic inside LifeOS. The external agent still decides
  what matters and what should change.
- Optimizing every read operation for very large vaults before profiling demonstrates a
  need.

# Acceptance criteria

- An MCP-only agent with no direct vault filesystem access can discover relevant vault
  paths, read canonical Markdown, search existing knowledge, follow useful context or
  references, and iteratively choose what to inspect next.
- A deterministic integration scenario proves a multi-step flow equivalent in capability
  to bounded `find`/`grep`/`cat` exploration without granting shell access.
- Existing read/search tools are reused where sufficient; new tools are added only for
  concrete capability gaps identified by the audit.
- All read operations enforce vault-root containment, privacy/routing policy, stable typed
  DTO boundaries, bounded outputs, and safe failure behavior.
- Authoritative read/discovery behavior does not depend on GNU-only or BSD/macOS-only shell
  utilities and uses portable Python/LifeOS abstractions so the same MCP contract can run on
  supported Linux and macOS hosts, including ARM64 Linux home-node targets.
- Canonical mutation remains unavailable through generic filesystem operations and continues
  to flow through LifeOS proposal/consequential authorization contracts.
- Tool descriptions/instructions clearly tell the agent that exploration is encouraged and
  semantic decisions belong to the agent, while mutation is constrained by LifeOS.
- Tests demonstrate that an agent can crawl broadly but cannot bypass ownership,
  provenance, proposal, or authorization rules to mutate canonical state.
- Local STDIO MCP behavior remains supported and existing MCP/integration tests remain green.
- User and architecture documentation describe the finalized read/write capability boundary.

# Documentation impact

Status: required

Implemented as a dedicated cross-cutting reference rather than scattering the finalized
contract across several broad chapters:

- `docs/mcp-exploration-architecture.md`: records the durable exploration-versus-mutation
  principle, the agent/MCP/core/vault responsibility boundary, privacy rules, output bounds,
  runtime composition, and proposal-only mutation path.
- `docs/user-manual/15-mcp-exploration.md`: documents the agent-facing tool inventory,
  iterative MCP-only exploration workflow, protected-scope behavior, and controlled mutation
  path.
- `docs/user-manual/README.md`: links the new manual chapter into the canonical reading path.

# Validation

Repository CI run #122 passed after the completed implementation and review-hardening rounds:

- documentation impact gate;
- Ruff repository gate;
- mypy over `src`;
- Python compileall over `src` and `tests`;
- manual link validation;
- full pytest suite;
- clean-room Docker setup and MCP gate.

The deterministic MCP STDIO test exercises a real `vault_list` → `vault_search` →
`vault_read_many` → `vault_links` crawl before continuing into `vault_context`. Mutation-boundary
tests assert that no generic write/delete/move/shell tool is exposed and that proposal
application remains consequential and authorized.

Review hardening additionally verifies policy-before-I/O traversal, symlink-safe policy loading,
external-disclosure enforcement, strict MCP inputs, deterministic list/link continuation,
link-syntax-aware canonical resolution, bounded search/multi-read metadata, explicit search/link
omission diagnostics, execution-versus-validation error classification, and policy-filtered
runtime activity paths. All review threads present before the final re-review request were
resolved after CI #122 passed.

# Implementation notes

- Added `vault_list`, `vault_search`, `vault_read_many`, and `vault_links` as bounded read-only
  MCP primitives over an authoritative Python exploration facade.
- Reused secure vault traversal, canonical retrieval policy, lexical search, Markdown parsing,
  link parsing, runtime activity, proposal lifecycle, ownership, and authorization contracts.
- Protected scopes remain default-deny for broad exploration. MCP disclosure requires both an
  explicit protected-read request and policy permission through `external_allowed_prefixes`;
  excluded prefixes remain unavailable.
- Existing focused reads, wiki search, and `vault_context` remain composable rather than being
  replaced by a monolithic ingestion tool.
- User-facing `runtime_activity` re-filters path metadata through current external policy so a
  previous protected-read grant cannot later leak protected path names.
- Semantic retrieval remains the existing derived subsystem. Direct MCP convergence with hybrid
  retrieval/context packs is intentionally left to LIFEOS-1642, which depends on this task.
- The user-facing STDIO runtime composes the existing core MCP server with the exploration
  surface; no network transport was introduced.

# Relevant decisions

- DD-033: SQLite/runtime-derived state remains disposable and rebuildable.
- DD-035: generated ownership remains canonical authorization data and fails closed.
- DD-036: Python remains the sole business-rule engine; MCP adapters do not reimplement
  authorization or mutation semantics.
- DD-087: MCP integration validation remains deterministic infrastructure testing without an
  LLM in the loop.
- DD-088: vault bootstrap remains first-party and does not mutate external client config.
- Existing secure vault traversal, privacy scopes, retrieval, proposal, provenance, and MCP
  routing/safety contracts remain authoritative and should be composed rather than forked.
