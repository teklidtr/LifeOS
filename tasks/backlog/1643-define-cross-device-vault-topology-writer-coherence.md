---
id: LIFEOS-1643
title: Define cross-device vault topology and writer coherence
status: backlog
phase: 16
depends_on:
  - LIFEOS-1639
risk: medium
---

# Goal

Define a safe, provider-neutral cross-device vault contract for the primary LifeOS use case:
one human user, multiple Obsidian-capable devices, and at most one active LifeOS mutation
authority at a time.

The user must remain free to create, edit, rename, move, and delete normal Markdown notes
manually in Obsidian. A synchronization provider may move those changes between devices.
LifeOS must notice the resulting filesystem state, preserve hash/provenance guarantees, and
fail closed when a proposal or write was based on a stale version.

This task does not build a synchronization product or a distributed multi-writer system. It
defines the coherence rules that LIFEOS-1640 can safely rely on.

# Design principles

- Assume one human user. Multi-user collaboration is not a requirement.
- The normal workflow has one active LifeOS mutation authority at a time.
- Human Markdown edits and offline captures remain first-class and do not require LifeOS
  commands or MCP to create/delete notes.
- A synchronized replica is not automatically a second independent LifeOS writer.
- Markdown remains canonical; `.lifeos/` indexes, registry, embeddings, caches, and other
  runtime state remain disposable and should normally stay local to the active LifeOS node.
- Sync transport and LifeOS consistency are separate concerns.
- Existing source hashes, target/base hashes, proposal application checks, Git history,
  ownership, provenance, and registry refresh behavior should be composed rather than
  replaced.
- If LifeOS cannot prove that the file it is about to mutate is still the version it reasoned
  about, it must stop rather than overwrite newer human or synchronized changes.
- The contract must remain provider-neutral. Obsidian Sync, Google Drive, Syncthing, mounted
  storage, Git-based transport, or another mechanism may be used outside LifeOS core.

# Scope

- Define supported topology classes for at minimum:
  - one desktop vault with local STDIO LifeOS;
  - an authoritative always-on LifeOS node with desktop/mobile human-facing synchronized
    copies;
  - an always-on LifeOS node operating on a mounted/shared canonical filesystem;
  - offline mobile capture that synchronizes later.
- Define the default writer model as one active LifeOS mutation endpoint for the synchronized
  vault view. Simultaneous independent LifeOS writers are unsupported in the initial design.
- Explicitly preserve normal manual Obsidian behavior: users may add, edit, rename, move, or
  delete notes directly. Registry/index state must reconcile from the filesystem rather than
  making the registry an authority over Markdown.
- Define how new, modified, renamed/moved, and deleted files are detected and reflected in
  disposable registry/index state after synchronization or manual editing.
- Specify stale protection for proposal/apply flows. If a source or target hash differs from
  the version used to prepare the operation, the operation must fail closed and require
  refresh/re-evaluation rather than silently applying to the new version.
- Define behavior for sync lag, conflict copies, partially synchronized source/target sets,
  interrupted sync, and a manual edit arriving after a proposal was drafted or approved.
- Define Git responsibility for the active LifeOS node without requiring every synchronized
  client to independently commit the vault.
- Define offline-first phone/university capture: a note created while disconnected becomes a
  normal canonical source after sync and registry/index reconciliation; the phone does not
  need to run LifeOS or MCP.
- Define how agent-created `raw/` research evidence from LIFEOS-1641 and human-created raw or
  study captures coexist under the same single-user coherence model.
- Add deterministic tests/simulations for manual add/edit/delete, stale proposal, delayed
  synchronized edit, conflict-file, rename/delete, and offline-capture arrival scenarios.
- Record a durable design decision if the single-user/single-active-LifeOS-writer rule becomes
  an architectural invariant needed by LIFEOS-1640.

# Out of scope

- Building or replacing Obsidian Sync, Google Drive, Syncthing, SMB/NFS, Git sync, or another
  file synchronization product.
- Multi-user collaboration semantics.
- CRDTs, distributed consensus, multi-master merge protocols, or distributed locks for
  simultaneous independent LifeOS writers.
- Requiring every sync provider to expose a freshness API.
- Running LifeOS or an LLM on the phone solely for offline capture.
- Making `.lifeos/` derived state canonical or synchronizing it as authoritative data.
- Implementing network MCP/home-node serving itself; that is LIFEOS-1640.

# Acceptance criteria

- The supported default is explicitly documented as one human user and one active LifeOS
  mutation authority at a time.
- Users can manually add, edit, rename/move, and delete ordinary vault Markdown without
  corrupting LifeOS state or needing a special LifeOS filesystem command.
- Registry/index state can reconcile manual and synchronized filesystem changes and remains
  disposable rather than authoritative.
- Human edits arriving after proposal creation invalidate stale source/target assumptions
  through hash/application-time checks instead of being overwritten.
- Offline phone capture has a documented path from local Markdown to synchronized canonical
  source to later LifeOS ingestion without MCP on the phone.
- Conflict-file, rename, delete, partial-sync, and sync-lag cases have explicit conservative
  behavior.
- Canonical Markdown/Git/proposal/ownership/provenance state is clearly separated from
  node-local disposable `.lifeos/` state.
- The design remains sync-provider-neutral and does not put Google Drive, Obsidian Sync, or
  another provider inside LifeOS core business rules.
- LIFEOS-1640 can consume the contract without inventing a distributed multi-writer system.
- Deterministic tests demonstrate manual filesystem changes plus stale/conflict safety at
  LifeOS boundaries.

# Documentation impact

Status: required

- `docs/architecture.md`: define the single-user cross-device topology, active LifeOS writer,
  manual-edit compatibility, and synchronization boundary.
- `docs/user-manual/04-setup-and-installation.md`: document supported vault placement/mount/
  sync patterns once finalized.
- `docs/user-manual/05-workflow.md`: document manual Obsidian edits, offline mobile capture,
  synchronization, and stale/conflict behavior from the user's perspective.
- `docs/design-decisions.md`: add a durable decision if the single-active-LifeOS-writer model
  is adopted as an architectural invariant.

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

- LIFEOS-1639: agents explore through rich LifeOS read surfaces while canonical mutations
  remain controlled.
- LIFEOS-1640: the always-on home node requires a coherent vault filesystem view but does not
  build a synchronization product.
- LIFEOS-1641: query-driven external research may create controlled raw evidence and must
  preserve lineage.
- DD-001: Markdown remains canonical.
- DD-031 through DD-035: proposal history, typed patches, disposable SQLite, application-time
  validation, and generated ownership remain authoritative.
- DD-038: direct UI writes use optimistic concurrency and stale writes fail closed.
- DD-061: retrieval/index state remains disposable and transactionally rebuildable.
- DD-088: `lifeos init` remains non-destructive vault bootstrap and does not configure
  external clients or deployment topology.
