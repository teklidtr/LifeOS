# Cross-device vault topology and writer coherence

LIFEOS-1643 defines the provider-neutral contract for using one canonical LifeOS vault from
multiple human devices without turning the core into a synchronization product or a distributed
write coordinator.

The governing rule is deliberately small:

> A human may edit the synchronized Markdown vault from multiple devices, but at most one active
> LifeOS runtime has mutation authority for that vault at a time.

This is the `single-active-lifeos-writer` model. Synchronization software transports files. It
does not grant LifeOS mutation authority, resolve proposal conflicts, or become a source of truth.

## State topology

| State | Authority | Cross-device treatment |
| --- | --- | --- |
| Canonical Markdown vault | Canonical | May be synchronized and backed up |
| Git history on the active LifeOS node | Canonical audit/recovery history | Managed by the active node; do not merge `.git/` through file sync |
| Proposal directories and reviewed proposal metadata | Canonical | Synchronized as ordinary canonical vault files |
| Generated ownership/provenance artifacts | Canonical | Synchronized with the Markdown they authorize or describe |
| Configured LifeOS runtime directory | Disposable | Node-local; when it lives under the vault, exclude that exact vault-relative directory from sync |
| Obsidian workspace state | Device-local UI state | Exclude `.obsidian/workspace*.json` from sync when possible |

`lifeos init` currently defaults runtime state to `<vault>/.lifeos`. That layout remains valid
because `.lifeos/` is explicitly disposable and ignored by Git. A deployment may configure a
different `runtime_dir`, including a different directory under the vault or a directory outside
the vault. `lifeos doctor` reports which topology is active and derives the runtime exclusion from
the configured path rather than assuming `.lifeos/`.

Required sync exclusions exposed by the coherence contract are:

- the configured `runtime_dir` as a vault-relative directory when runtime state lives under the
  canonical vault, for example `.lifeos/` by default or `runtime/node-a/` for a custom layout,
- `.git/`,
- `.obsidian/workspace*.json`.

When `runtime_dir` is outside the canonical vault there is no runtime-directory sync exclusion to
apply inside the vault. A sync provider may require additional provider-specific exclusions. Those
remain deployment configuration rather than LifeOS business rules.

## Note identity is not a path

For relocation-safe canonical notes, three facts are intentionally separate:

1. **Stable note identity**: durable frontmatter `id`.
2. **Current path**: the note's present vault-relative location.
3. **Content version**: SHA-256 of the exact canonical bytes currently observed.

A rename therefore changes the path without changing identity. An edit changes the content hash
without changing identity. A rename plus edit changes both path and content hash while retaining
the same identity.

Stable IDs are selective, consistent with DD-006. Existing wiki notes without an `id` remain
usable and path-addressable, but LifeOS reports that their relocation continuity is not provable.
They can gain a stable ID through an explicit migration. Once the registry has observed a stable
ID for a note at a path, removing or replacing that ID in place is treated as an identity change
and fails closed while that registry row represents an active note.

Duplicate stable IDs are never guessed through within the scope where LifeOS is allowed to
resolve identity. An unscoped local refresh or `lifeos doctor` blocks a canonical collision with
`stable-id-ambiguous`. A policy-scoped external refresh first excludes denied paths from identity
resolution, without opening their content, so an unrelated protected note cannot make a public
identity result disclose or depend on protected content merely because it carries the same ID.

## Registry reconciliation

The SQLite registry remains disposable under DD-033. Refresh derives its identity map from the
canonical Markdown view:

`stable id -> current path -> current content hash`

Relocations are reconciled as a scan set rather than one path at a time. All moving stable
identities reserve their existing registry rows before final paths are assigned, so two-note swaps
and longer path cycles preserve every surviving `files.id` and its foreign-keyed provenance or
source-version lineage. Pure moves are reported separately from new/deleted files. Move-plus-edit
records both relocation and modification.

A path that belonged to a note which was already confirmed deleted may later be reused by a new
stable identity. The deleted historical row remains a disposable tombstone while the new note gets
a new registry row. This is distinct from changing the stable ID of an active note in place, which
still fails closed.

The registry indexes `stable_id` for lookup but does not impose global SQLite uniqueness on that
column. This is deliberate: a policy-scoped refresh may preserve previously observed hidden
lineage while recording a visible note without allowing the hidden row to influence the scoped
identity decision. Uniqueness is therefore proved at the caller-authorized canonical resolution
boundary, where more than one matching visible note fails closed. The disposable database is not
used as a shortcut around retrieval policy or as proof that canonical IDs are globally valid.

Non-Markdown attachments continue to hash through streamed reads without retaining their complete
bytes merely for stable-ID extraction. Markdown participating in stable identity derives ID, hash,
size, and mtime from one observed byte stream. Rebuilding the database from Markdown must
reproduce the same active identity facts.

The registry is not a distributed lock and is not authoritative identity storage. Frontmatter
and current canonical bytes remain the evidence.

## Proposal coherence across moves

Typed patch operations keep their reviewed path and base hash. Replacement operations may also
retain the target stable ID in the review-bound `lifeos_target_identity` proposal metadata
extension. Create operations remain path-oriented because there is no pre-existing note identity
to follow.

The extension does not weaken existing stale-write protection. It adds enough evidence to explain
what happened after a synchronized or manual move:

| Current state | Result |
| --- | --- |
| Same ID, same path, same reviewed hash | Current target; ordinary validation may continue |
| Same ID, new path, same hash, proposal still draft | Draft rebase is possible only through an explicit workflow that revalidates the new path and regenerates review material |
| Same ID, new path, same hash, proposal pending/approved | Do not silently retarget; renewed review/approval is required |
| Same ID, changed hash | Stale content; existing base-hash protection remains authoritative |
| Expected ID missing | Missing target; fail closed |
| Reviewed path now has another ID | Identity changed; fail closed |
| Same ID resolves to multiple policy-visible paths | Ambiguous identity; fail closed |

Proposal identity discovery applies retrieval policy to path metadata before unrelated Markdown is
opened. An explicitly reviewed target can authorize protected-scope intent for that exact target,
but unrelated protected or excluded notes are neither read nor allowed to influence a public
target's preflight result merely because they share an ID.

A move can change path-scoped privacy, routing, generated ownership, or authorization semantics.
Stable identity therefore proves continuity of the note, not permission to mutate its new path.
Any explicit draft rebase must rerun those path-scoped checks before producing a new review
snapshot.

## Retrieval identity exposure

Retrieval exposes a stable ID only when the active retrieval index can represent that durable ID
uniquely and the returned canonical path still contains the same ID and exact indexed content
hash. If two policy-visible indexed notes share an ID, both remain indexed with path-derived
document keys so the SQLite primary key cannot hide either collision. Introducing or resolving a
duplicate during incremental synchronization re-identifies unchanged affected notes as needed.

Search-time identity verification reads only returned stable-ID candidates. It does not rescan and
rehash the whole vault for every query, and it does not reopen a mutable active-index path after
the base search snapshot closes.

## Offline and synchronized-device workflow

A safe ordinary workflow is:

1. Keep one machine or service as the active LifeOS writer.
2. Let the sync provider finish delivering canonical Markdown changes before running consequential
   LifeOS mutations on the active writer.
3. Run `lifeos doctor --config <path>` after changing topology or when duplicate/missing identity
   diagnostics are suspected.
4. Refresh disposable registry/retrieval state from the canonical vault after incoming changes.
   Registry refresh output includes explicit old-path/new-path rename pairs so operators and MCP
   clients can distinguish relocations from create/delete churn.
5. Treat proposals whose targets moved or changed as needing deterministic reassessment. Never
   patch the new path merely because a filename resembles the old one.
6. If the active writer is changed to another node, stop mutation activity on the old node first,
   synchronize canonical state, then rebuild disposable state on the new writer.

There is intentionally no lease protocol, distributed lock, network home-node service, or
sync-provider adapter in this task. Those would add failure modes before the single-writer contract
has a concrete deployment need.

## Recovery and conflict handling

- **Interrupted sync / partial filesystem view:** do not perform consequential mutations until the
  provider has reached a coherent canonical view. Rebuild disposable indexes afterward.
- **Duplicate IDs:** repair the canonical Markdown collision first; do not repair SQLite by hand.
- **Move plus edit:** stable ID can establish note continuity, but the changed content hash makes an
  already-reviewed replacement stale.
- **Proposal target move:** drafts may be explicitly rebased with path policy/ownership rechecks;
  pending or approved proposals require renewed review.
- **Deleted note:** stable identity becomes missing. A different path without the same stable ID is
  not assumed to be the replacement.
- **Disposable-state corruption:** delete/rebuild node-local state from canonical Markdown and Git
  history rather than treating the configured runtime directory as authoritative.

## Operator diagnostics

`lifeos doctor` exposes a `coherence` section in JSON and a corresponding text section with:

- writer model,
- canonical vault and runtime locations,
- whether runtime state is inside the synchronized vault tree,
- required sync exclusions, including the configured vault-relative runtime directory when
  applicable,
- count of relocation-safe Markdown identities,
- warnings for legacy wiki notes without stable IDs,
- blocking diagnostics for duplicate stable IDs.

This keeps deployment assumptions visible without teaching core LifeOS about Dropbox, Syncthing,
iCloud, Git remotes, or any other transport.

## Relationship to existing decisions

This contract composes rather than replaces existing decisions:

- DD-001: Markdown remains canonical.
- DD-006: stable IDs are selective.
- DD-011 and DD-012: read-before-write and scripted preservation checks remain mandatory.
- DD-033: SQLite remains disposable and rebuildable.
- DD-034: approval does not bypass application-time stale validation.
- DD-038: existing-target mutations use optimistic concurrency/content hashes.
- DD-061: retrieval state remains disposable and transactionally rebuildable.

The new cross-device rule is: **stable identity establishes continuity; current path establishes
scope; content hash establishes the reviewed version. None substitutes for the other two.**
