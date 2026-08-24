# Cross-Device Vault Coherence

[← Previous: MCP Exploration and Controlled Mutation](15-mcp-exploration.md) · [Manual home](README.md)

LifeOS can use a vault that is synchronized across your laptop, desktop, phone, or tablet, but
there is an important boundary: **only one LifeOS runtime should have mutation authority for that
vault at a time**. Other devices may still edit ordinary Markdown manually.

This is not a requirement to use any particular synchronization service. LifeOS treats sync as
transport and keeps its own safety rules provider-neutral.

## What should sync

The canonical vault content should travel between devices: your Markdown, proposals, durable
ownership/provenance files, and other ordinary canonical vault artifacts.

Do **not** treat these as shared authoritative state:

- `.lifeos/` registry, retrieval indexes, embeddings, journals, and temporary runtime state
- `.git/` internals through a file-sync merge
- `.obsidian/workspace*.json` device-specific workspace state

A default `lifeos init` keeps runtime files at `<vault>/.lifeos`. That is fine as long as `.lifeos/`
is excluded from synchronization. You can also configure `runtime_dir` outside the vault.

## Check the topology

Run:

```bash
lifeos doctor --config /path/to/lifeos.yml
```

The report includes a **Cross-device coherence** section. In JSON mode the same information lives
under `coherence`:

```bash
lifeos doctor --config /path/to/lifeos.yml --json
```

Look for:

- `writer_model: single-active-lifeos-writer`
- whether runtime state is `inside-canonical-vault` or `node-local-outside-vault`
- required synchronization exclusions
- stable identity diagnostics

A warning that runtime state is inside the vault is expected for the default layout. It means the
`.lifeos/` exclusion matters; it does not mean the vault is unhealthy.

## Renaming and moving notes

LifeOS distinguishes three things:

- the note's durable frontmatter `id`,
- its current vault-relative path,
- the SHA-256 hash of its current bytes.

For example, this note:

```yaml
---
id: concept-sleep-pressure
type: concept
title: Sleep pressure
---
```

may move from `wiki/concepts/sleep-pressure.md` to `wiki/concepts/sleep/homeostatic-pressure.md`
without becoming a different note. The stable `id` preserves identity; the path records where it
lives now.

If you edit it at the same time, its content hash changes. LifeOS can still recognize the same
identity, but any proposal reviewed against the old hash is stale.

## Legacy notes without IDs

Stable IDs remain selective. LifeOS does not require IDs for every scratch note, daily note, raw
import, or attachment.

Wiki notes without an ID remain usable, but `doctor` warns that a move cannot be followed safely by
identity alone. Add a durable ID through a deliberate migration when a legacy wiki note becomes an
important long-lived target.

Once LifeOS has registered a stable ID for a note, removing or replacing that ID in place is
considered an identity change and registry refresh fails closed. This prevents a quiet identity
swap from looking like an ordinary edit.

## Duplicate IDs

Two current Markdown notes must not claim the same stable ID. If they do:

- registry refresh stops before changing registry state,
- `lifeos doctor` reports `stable-id-ambiguous`,
- relocation-aware mutation should remain blocked.

Repair the Markdown IDs first, then rebuild disposable state. Do not manually edit SQLite to make
the warning disappear.

## What happens to proposals when a target moves

Replacement proposals may remember the target's stable identity in review-bound metadata, but the
patch still retains its reviewed path and content hash.

That gives conservative behavior:

- **Draft + moved + unchanged content:** an explicit rebase workflow may move the draft forward,
  but it must recheck rules for the new path and regenerate the review material.
- **Pending or approved + moved + unchanged content:** renewed review is required. LifeOS must not
  silently retarget an approval to a new path.
- **Moved + edited:** stale. The old reviewed hash no longer describes current content.
- **Duplicate/missing identity:** blocked until the ambiguity is resolved.

This matters because a move may cross privacy, ownership, routing, or authorization boundaries.
Stable identity proves "same note", not "same permission".

## Working offline on another device

You can edit Markdown while a device is offline. Before running consequential LifeOS mutations on
the active writer after that device reconnects:

1. Let synchronization finish delivering its Markdown changes.
2. Resolve provider-level file conflicts instead of asking LifeOS to guess which copy wins.
3. Run `lifeos doctor` if topology or identity conflicts are in doubt.
4. Refresh disposable registry/retrieval state from the canonical filesystem view.
5. Re-review proposals whose targets moved or whose content hashes changed.

If you want to transfer LifeOS mutation authority to a different machine, stop mutation activity on
the old writer, synchronize the canonical vault, then rebuild disposable state on the new writer.
Do not run two independent LifeOS writers and hope the sync provider acts as a distributed lock.

## Recovery rules

When something looks inconsistent, prefer rebuilding derived state over repairing it by hand:

- canonical Markdown and Git history are durable evidence,
- `.lifeos/` is disposable,
- stable IDs are read from canonical frontmatter,
- current paths are discovered from the current filesystem,
- content hashes are recomputed from current bytes.

For the full architecture contract and failure-mode table, see
[Cross-device vault topology and writer coherence](../cross-device-vault-coherence.md).

---

[← Previous: MCP Exploration and Controlled Mutation](15-mcp-exploration.md) · [Manual home](README.md)
