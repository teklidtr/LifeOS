---
id: LIFEOS-1639
title: Expand MCP exploration and controlled mutation surface
status: in-progress
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

- `docs/architecture.md`: record the durable principle that LifeOS constrains mutation, not
  exploration, and define the agent/MCP/core/vault responsibility boundary.
- `docs/user-manual/03-feature-breakdown.md`: explain the agent-facing exploration and
  controlled-mutation capabilities.
- `docs/user-manual/05-workflow.md`: document iterative MCP-only vault exploration and the
  proposal-based write path.
- MCP setup/reference documentation affected by the finalized tool inventory must be updated
  in the same PR.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/mcp tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

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
