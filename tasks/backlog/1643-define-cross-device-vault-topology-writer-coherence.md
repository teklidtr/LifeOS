---
id: LIFEOS-1643
title: Define cross-device vault topology and writer coherence
status: backlog
phase: 16
depends_on:
  - LIFEOS-1639
risk: high
---

# Goal

Define a safe, provider-neutral vault topology for a LifeOS home node plus Obsidian/mobile/
desktop clients so the same canonical Markdown knowledge base can be captured and edited
across devices without allowing divergent replicas or simultaneous writers to bypass LifeOS
hash, proposal, ownership, provenance, and recovery guarantees.

This task defines the coherence contract that an always-on deployment such as LIFEOS-1640
must rely on. It does not build a new file-synchronization product.

# Design principles

- Markdown remains canonical regardless of which device presents it to the user.
- MCP answers how an agent calls LifeOS; synchronization answers how devices obtain a
  coherent view of canonical files. These are separate concerns.
- A synchronized replica is not automatically an independent LifeOS mutation authority.
- Agent mutations should occur against one explicitly configured authoritative LifeOS vault
  view unless a future multi-writer protocol can prove equivalent safety.
- Human capture should remain offline-first where practical; intelligence may be
  online-when-available.
- Sync delay, conflicts, renames, deletions, and stale replicas must fail visibly rather than
  silently creating contradictory canonical histories.
- Existing proposal base hashes, source hashes, Git history, ownership, and recovery
  machinery should be composed rather than replaced.
- The contract must be sync-provider-neutral. Obsidian Sync, Git-based sync, mounted storage,
  file replication, or another mechanism may satisfy it if they meet the same invariants.

# Scope

- Define supported topology classes for at minimum:
  - one local desktop vault with local STDIO LifeOS;
  - an authoritative always-on LifeOS node with desktop/mobile human-facing replicas;
  - an always-on LifeOS node operating on a mounted/shared canonical filesystem;
  - offline mobile capture that synchronizes later.
- Decide and document the default writer model for the home-node architecture. Prefer a
  single authoritative LifeOS mutation endpoint unless evidence shows a safe multi-writer
  model is required.
- Distinguish:
  - human edits/captures performed in Obsidian or another Markdown client;
  - agent mutations performed through LifeOS;
  - derived/rebuildable runtime state local to each runtime;
  - synchronization transport/provider state.
- Define what it means for the home node to have a sufficiently coherent filesystem view
  before LifeOS reads, builds proposals, or applies mutations.
- Specify how existing hash-based concurrency semantics behave when a human edit arrives from
  another device after a proposal was drafted or approved. Stale targets must continue to
  fail closed rather than being overwritten.
- Define behavior for sync lag, simultaneous edits, file conflicts, renames, moves, deletions,
  duplicate conflict files, partially synchronized source/target sets, and interrupted sync.
- Define how Git interacts with synchronized replicas so Git history remains useful without
  assuming that every client independently commits or mutates the same repository.
- Determine whether sync/provider health or freshness can be observed generically. If a
  provider cannot prove freshness, document the weaker guarantees and the operations that
  must remain conservative.
- Define offline-first phone/university capture semantics. A user should be able to capture
  notes while disconnected and have them become normal canonical sources after synchronization
  without requiring the phone to run LifeOS or MCP.
- Define how agent-created `raw/` research evidence from LIFEOS-1641 and human-created raw/
  study captures coexist under the same synchronization/coherence rules.
- Establish a portable deployment contract for persistent vault data versus node-local
  `.lifeos/` derived state. Derived indexes/caches should normally rebuild on the active
  LifeOS node instead of being synchronously replicated as canonical data.
- Add deterministic simulation/integration tests for stale replica, concurrent human edit,
  rename/delete, conflict-file, and offline-capture arrival scenarios where the chosen
  contract can be tested without a real third-party sync service.
- Produce a durable design decision before LIFEOS-1640 finalizes service deployment if the
  chosen writer/topology model creates a new architectural invariant.

# Out of scope

- Building a replacement for Obsidian Sync, Syncthing, Git synchronization, SMB/NFS, cloud
  drive replication, or another general-purpose synchronization product.
- Requiring every supported sync provider to expose identical freshness APIs.
- Running LifeOS or an LLM on the phone solely to support offline capture.
- Making `.lifeos/` derived indexes, embeddings, SQLite, or caches canonical synchronized
  state.
- Allowing multiple independent LifeOS nodes to mutate divergent replicas merely because the
  files may eventually synchronize.
- Solving distributed consensus for arbitrary multi-master filesystems.
- Implementing network MCP/home-node serving itself; that is LIFEOS-1640.

# Acceptance criteria

- Architecture documentation identifies the supported home-node/mobile/desktop vault
  topologies and clearly names the default authoritative LifeOS mutation location.
- A synchronized desktop/mobile copy is not accidentally treated as a second unrestricted
  LifeOS writer.
- Human edits arriving from another device invalidate stale proposal/apply operations through
  existing hash/concurrency checks rather than being overwritten.
- Rename, delete, conflict-file, and partial-sync cases have explicit conservative behavior.
- Offline phone capture has a documented path from local Markdown capture to synchronized
  canonical source to later LifeOS ingestion without requiring MCP on the phone.
- Canonical Markdown/Git/proposal/ownership/provenance state is separated from node-local
  disposable `.lifeos/` retrieval/registry/runtime state.
- The design remains provider-neutral and does not make Obsidian Sync or any other third-party
  synchronization mechanism part of LifeOS core business rules.
- LIFEOS-1640 can consume the resulting topology/coherence contract without inventing a
  second synchronization model inside service deployment code.
- Deterministic tests or fixtures demonstrate the chosen stale/conflict semantics where they
  are implementable at LifeOS boundaries.

# Documentation impact

Status: required

- `docs/architecture.md`: define canonical vault topology, authoritative writer semantics,
  replica/coherence boundaries, and how these interact with MCP and the home node.
- `docs/user-manual/04-setup-and-installation.md`: document supported vault placement/mount/
  sync patterns once finalized.
- `docs/user-manual/05-workflow.md`: document offline mobile capture, synchronization, and
  stale/conflict behavior from the user's perspective.
- `docs/design-decisions.md`: add a durable decision if a single-writer or other cross-device
  coherence invariant is adopted.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/integration tests/proposals tests/mcp
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- LIFEOS-1639: remote/local agents should interact through rich LifeOS exploration tools and
  controlled mutations rather than arbitrary vault filesystem access.
- LIFEOS-1640: the always-on home node requires a coherent vault filesystem view but does not
  build a synchronization product.
- LIFEOS-1641: query-driven external research may create controlled raw evidence on the
  authoritative LifeOS side and must preserve lineage.
- DD-001: Markdown remains canonical.
- DD-031 through DD-035: proposal history, typed patches, disposable SQLite, application-time
  validation, and generated ownership remain authoritative.
- DD-038: direct UI writes use optimistic concurrency and stale writes fail closed.
- DD-061: retrieval/index state remains disposable and transactionally rebuildable.
- DD-088: `lifeos init` remains non-destructive vault bootstrap and does not configure
  external clients or deployment topology.
