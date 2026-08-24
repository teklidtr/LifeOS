---
id: LIFEOS-1643
title: Define cross-device vault topology and writer coherence
status: in-progress
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

The design must also distinguish a note's durable identity from its current filesystem
address. A move or rename should not automatically make an otherwise unchanged canonical
note unknowable to LifeOS merely because its path changed.

This task does not build a synchronization product or a distributed multi-writer system. It
defines the coherence and note-identity rules that LIFEOS-1640 can safely rely on.

# Design principles

- Assume one human user. Multi-user collaboration is not a requirement.
- The normal workflow has one active LifeOS mutation authority at a time.
- Human Markdown edits and offline captures remain first-class and do not require LifeOS
  commands or MCP to create/delete notes.
- A synchronized replica is not automatically a second independent LifeOS writer.
- Markdown remains canonical; `.lifeos/` indexes, registry, embeddings, caches, and other
  runtime state remain disposable and should normally stay local to the active LifeOS node.
- Sync transport and LifeOS consistency are separate concerns.
- Treat canonical note identity, current path, and content version as separate concepts:
  - stable note ID answers **which canonical note is this?**;
  - current vault path answers **where is it now?**;
  - content hash answers **which version is this?**.
- Prefer an existing canonical frontmatter `id` as stable note identity where the artifact
  class supports one. Define an explicit migration/fallback contract for legacy notes that
  lack stable IDs rather than silently pretending a path is permanent identity.
- Stable IDs must be unique within the scope in which LifeOS resolves them. Duplicate or
  ambiguous IDs fail closed.
- Existing source hashes, target/base hashes, proposal application checks, Git history,
  ownership, provenance, and registry refresh behavior should be composed rather than
  replaced.
- If LifeOS cannot prove that the note it is about to mutate is the same note and still the
  version it reasoned about, it must stop rather than overwrite newer human or synchronized
  changes.
- Path changes may alter path-scoped instructions, privacy/routing policy, ownership, or
  other authorization context. Resolving the same stable ID at a new path never bypasses
  those checks.
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
- Define a canonical note identity contract and which artifact classes require or support a
  stable frontmatter ID. At minimum, durable wiki notes and other proposal-addressable
  canonical notes that need rename/move continuity must have a deterministic identity story.
- Define registry/index support for rebuilding a mapping such as:

  ```text
  stable note id -> current vault path -> current content hash
  ```

  without making the mapping itself canonical.
- Define how new, modified, renamed/moved, and deleted files are detected and reflected in
  disposable registry/index state after synchronization or manual editing. A disappearing
  path plus a unique stable ID appearing at a new path should be recognizable as relocation
  when safety checks prove it is the same note.
- Define proposal target addressing for existing notes so proposal state can retain, where
  applicable:
  - stable target note ID;
  - reviewed/current target path;
  - base content hash.
- Specify relocation behavior for a proposal whose target path changed after proposal
  creation:
  - if the old path is gone, LifeOS may resolve the stable target ID within the allowed scope;
  - resolution must produce exactly one valid current note;
  - the resolved note must satisfy the proposal's reviewed base-hash/version assumptions;
  - path-scoped instructions, privacy/routing, ownership, authorization, and target-type rules
    must be re-evaluated at the new path;
  - a path relocation must never silently turn an approved operation into an unreviewed
    operation against a materially different context.
- Define lifecycle-safe rebase/review behavior after relocation. A draft may be deterministically
  rebased to the new path with a regenerated review snapshot when all invariants still hold.
  Pending or approved proposals must not silently retarget; relocation should require an
  explicit renewed review/approval path unless a future durable design decision proves a
  narrower path-neutral case safe.
- Treat stable-ID mutation as an identity change, not an ordinary rename. Proposal application
  must fail closed if the expected target ID disappeared, changed, became duplicated, or
  resolves ambiguously.
- Preserve strict stale protection for content edits. Same stable ID at the same or a new path
  with a different content hash is a changed version and requires refresh/re-evaluation; ID
  resolution must not weaken base-hash protection.
- Keep create operations path-oriented when the target is intentionally absent; stable-ID
  relocation semantics apply to identifying existing canonical notes, not to guessing where
  a new file should be created.
- Define behavior for sync lag, conflict copies, partially synchronized source/target sets,
  interrupted sync, and a manual edit arriving after a proposal was drafted or approved.
- Define Git responsibility for the active LifeOS node without requiring every synchronized
  client to independently commit the vault.
- Define offline-first phone/university capture: a note created while disconnected becomes a
  normal canonical source after sync and registry/index reconciliation; the phone does not
  need to run LifeOS or MCP.
- Define how agent-created `raw/` research evidence from LIFEOS-1641 and human-created raw or
  study captures coexist under the same single-user coherence model.
- Ensure retrieval/MCP surfaces can expose both stable note ID and current path where that
  distinction materially helps agents follow notes across relocation, without forcing agents
  to treat path as permanent semantic identity.
- Add deterministic tests/simulations for manual add/edit/delete, stale proposal, delayed
  synchronized edit, conflict-file, rename/delete, offline-capture arrival, stable-ID
  relocation, duplicate-ID ambiguity, and content-changed-after-relocation scenarios.
- Record a durable design decision if the single-user/single-active-LifeOS-writer rule or the
  stable-note-identity contract becomes an architectural invariant needed by LIFEOS-1640.

# Out of scope

- Building or replacing Obsidian Sync, Google Drive, Syncthing, SMB/NFS, Git sync, or another
  file synchronization product.
- Multi-user collaboration semantics.
- CRDTs, distributed consensus, multi-master merge protocols, or distributed locks for
  simultaneous independent LifeOS writers.
- Requiring every sync provider to expose a freshness API.
- Running LifeOS or an LLM on the phone solely for offline capture.
- Making `.lifeos/` derived state canonical or synchronizing it as authoritative data.
- Silently applying an approved proposal to a newly resolved path without re-validating the
  review and authorization context.
- Treating content hash alone as durable note identity; two notes may legitimately have the
  same content.
- Implementing network MCP/home-node serving itself; that is LIFEOS-1640.

# Acceptance criteria

- The supported default is explicitly documented as one human user and one active LifeOS
  mutation authority at a time.
- Users can manually add, edit, rename/move, and delete ordinary vault Markdown without
  corrupting LifeOS state or needing a special LifeOS filesystem command.
- The architecture clearly distinguishes stable note ID, current vault path, and content hash
  and defines which canonical artifact classes use stable IDs.
- Registry/index state can rebuild a unique stable-ID-to-current-path mapping where supported
  and remains disposable rather than authoritative.
- Duplicate/ambiguous stable IDs fail closed and produce inspectable diagnostics.
- A pure rename/move of an unchanged identified note can be recognized as relocation rather
  than being indistinguishable from permanent deletion plus unrelated creation.
- Proposal operations against existing identified notes can retain stable target identity,
  reviewed path, and base hash without weakening path containment or hash checks.
- If a proposal target relocates with the same stable ID and same reviewed content version,
  LifeOS can resolve the current target but re-validates path-scoped instructions, privacy,
  ownership, authorization, and review context before any mutation.
- Pending/approved proposals are never silently retargeted after relocation. The chosen
  deterministic rebase/re-review behavior is documented and tested.
- Same stable ID with a changed content hash remains stale and cannot be applied merely because
  identity resolution succeeded.
- Human edits arriving after proposal creation invalidate stale source/target assumptions
  through hash/application-time checks instead of being overwritten.
- Offline phone capture has a documented path from local Markdown to synchronized canonical
  source to later LifeOS ingestion without MCP on the phone.
- Conflict-file, rename, delete, partial-sync, and sync-lag cases have explicit conservative
  behavior.
- Canonical Markdown/Git/proposal/ownership/provenance state is clearly separated from
  node-local disposable `.lifeos/` state.
- Retrieval/MCP results expose stable ID plus current path where supported and useful for
  relocation-safe agent workflows.
- The design remains sync-provider-neutral and does not put Google Drive, Obsidian Sync, or
  another provider inside LifeOS core business rules.
- LIFEOS-1640 can consume the contract without inventing a distributed multi-writer system.
- Deterministic tests demonstrate manual filesystem changes plus identity, relocation,
  stale-version, review, and conflict safety at LifeOS boundaries.

# Documentation impact

Status: required

- `docs/architecture.md`: define the single-user cross-device topology, active LifeOS writer,
  manual-edit compatibility, stable-note-identity/current-path/content-hash model, and
  synchronization boundary.
- `docs/user-manual/04-setup-and-installation.md`: document supported vault placement/mount/
  sync patterns once finalized.
- `docs/user-manual/05-workflow.md`: document manual Obsidian edits, renames/moves, offline
  mobile capture, synchronization, and stale/relocated proposal behavior from the user's
  perspective.
- `docs/design-decisions.md`: add durable decisions for the single-active-LifeOS-writer model
  and stable canonical note identity if adopted as architectural invariants.

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
- LIFEOS-1642: context/retrieval convergence should be able to expose stable note identity
  independently from current path when useful.
- DD-001: Markdown remains canonical.
- DD-031 through DD-035: proposal history, typed patches, disposable SQLite, application-time
  validation, and generated ownership remain authoritative.
- DD-038: direct UI writes use optimistic concurrency and stale writes fail closed.
- DD-061: retrieval/index state remains disposable and transactionally rebuildable.
- Existing graph behavior already prefers frontmatter `id` as node identity and falls back to
  path when absent; LIFEOS-1643 must decide how that concept becomes a broader canonical-note
  identity contract without making the graph index authoritative.
- DD-088: `lifeos init` remains non-destructive vault bootstrap and does not configure
  external clients or deployment topology.
