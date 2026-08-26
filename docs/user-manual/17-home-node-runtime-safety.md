[← Previous: Cross-Device Vault Coherence](16-cross-device-vault-coherence.md) · [Manual home](README.md)

# 17. Home-Node Runtime Safety

The always-on `lifeos serve` process treats its configured runtime directory as disposable
node-local state, but it must never let that path become a route into canonical Markdown.
The home-node service therefore binds the runtime directory to one directory inode when the
process starts instead of trusting the pathname again for each registry or activity write.

## Pinned runtime authority

At startup, `lifeos serve` opens the configured `runtime_dir` through no-follow directory
operations and keeps that directory descriptor for the lifetime of the process. The home-node
registry and MCP activity stores use that pinned directory authority for their writes. A later
rename, mount replacement, or symlink at the configured runtime pathname cannot redirect those
writes into `wiki/`, `journal/`, `proposals/`, or another canonical subtree.

`/readyz` also revalidates that the configured pathname still selects the directory inode that
was pinned at startup. If the path is replaced, becomes a symlink, disappears, or selects a
different directory, authenticated readiness returns HTTP 503. Repair the mount/path and restart
the service so it can bind a fresh runtime authority. Do not try to make a running process adopt
a replacement runtime directory implicitly.

The generic local STDIO deployment is unchanged. This descriptor-pinned runtime contract belongs
to the long-lived Linux home-node service, where filesystem topology can change while the process
remains alive.

## Linux requirement

The current home-node implementation binds SQLite registry access through the pinned directory
descriptor using Linux `/proc/self/fd`. `lifeos serve` therefore fails closed at startup when that
facility is unavailable. The supplied OCI/Compose deployment and the Home Assistant Yellow Linux
path satisfy this requirement.

This Linux requirement is specific to the current always-on service implementation. Canonical
Markdown remains portable and does not depend on `/proc` or SQLite.

## Recovery after runtime replacement

When `/readyz` reports 503 after a runtime mount or path change:

1. Stop the home-node process or container.
2. Restore the intended non-symlink runtime directory or runtime volume.
3. Start `lifeos serve` again.
4. Confirm authenticated `/readyz` returns 200.
5. If disposable state was removed, call the normal authenticated MCP `registry_refresh` or let
   proposal-building ingestion perform its registry preflight.

Deleting or rebuilding runtime state must not alter canonical Markdown, proposal history,
generated ownership, provenance, or Git history. The full-validation home-node container gate
deletes runtime state and performs a real authenticated `registry_refresh` to verify this
rebuildability contract.

---

[← Previous: Cross-Device Vault Coherence](16-cross-device-vault-coherence.md) · [Manual home](README.md)
