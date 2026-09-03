---
id: LIFEOS-1003
title: Create the desktop Obsidian plugin shell
status: completed
phase: 10
depends_on:
  - LIFEOS-1000
  - LIFEOS-1002
risk: medium
---

# Goal

Create a thin desktop Obsidian plugin that manages the LifeOS bridge connection,
registers views and commands, and establishes reusable UI foundations without
implementing business rules in TypeScript.

# Scope

- Add a dedicated TypeScript plugin package and reproducible build tooling.
- Register a LifeOS ribbon action, command-palette entries, and dockable view.
- Add settings for configuration path, Python/launcher path when needed, actor
  display identity, startup behavior, and diagnostic verbosity.
- Start or connect to the local bridge according to LIFEOS-1000.
- Show connection states: starting, connected, degraded, incompatible,
  unavailable, and stopped.
- Add a typed protocol client generated from or checked against the Python
  contract.
- Add shared components for loading, empty, stale, blocked, error, and retry
  states.
- Add safe invalidation handling so views refresh after canonical changes.
- Ensure plugin unload stops owned processes and unsubscribes listeners.
- Provide a developer fixture vault and plugin test harness.

# Out of scope

- Today dashboard content.
- Quick capture forms.
- Task updates.
- Proposal approval.
- Mobile support.
- Replicating Markdown parsing or planning logic in TypeScript.

# Required invariants

- The plugin remains a presentation and interaction adapter.
- Plugin cache and UI preferences are not canonical LifeOS state.
- Connection failure never blocks normal Obsidian editing.
- No protocol secret, API key, or private note content is written to console
  logs by default.
- The plugin does not silently download or execute an untrusted Python binary.

# Required tests

- Plugin load and unload lifecycle.
- Successful bridge startup and clean shutdown.
- Missing Python or invalid config produces actionable UI.
- Protocol mismatch produces a non-destructive blocked state.
- Bridge crash changes connection state and offers retry.
- Repeated reload does not leak processes or event handlers.
- Commands and ribbon actions open the expected view.

# Acceptance criteria

- The plugin installs into a fixture vault and connects without terminal use.
- Shared UI states are reusable by later dashboard tasks.
- TypeScript lint, type-check, unit tests, and production build pass.

# Validation commands

```bash
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
pytest tests/bridge -q
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-007: Native Obsidian references first
