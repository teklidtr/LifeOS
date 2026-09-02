[← Previous: Cross-Device Vault Coherence](16-cross-device-vault-coherence.md) · [Manual home](README.md) · [Next: Evidence-Grounded Research →](18-evidence-grounded-research.md)

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

Runtime entries are treated as disposable files rather than trusted paths. The registry opens
`registry.db` itself with no-follow descriptor-relative operations, verifies that the opened inode
is a single-link regular file, and gives SQLite the pinned file descriptor rather than reopening
the validated pathname. This closes the validation/open race even if another local process changes
the runtime directory concurrently. Writable descriptor-bound registry connections use SQLite's
in-memory journal because the registry is rebuildable disposable state; no `registry.db-journal`
sidecar is trusted or required for canonical durability. LifeOS also rejects special-file,
symlink, multiply hard-linked, and oversized `activity/mcp.jsonl` entries instead of reading from
or appending through them. If a registry or activity entry has been replaced, hard-linked, or
grown beyond the bounded reader's 8 MiB limit unexpectedly,
remove or rebuild that disposable runtime entry rather than trying to preserve it as canonical
history.

`/readyz` also revalidates that the configured pathname still selects the directory inode that
was pinned at startup. If the path is replaced, becomes a symlink, disappears, or selects a
different directory, authenticated readiness returns HTTP 503. Repair the mount/path and restart
the service so it can bind a fresh runtime authority. Do not try to make a running process adopt
a replacement runtime directory implicitly.

The generic local STDIO deployment is unchanged. This descriptor-pinned runtime contract belongs
to the long-lived Linux home-node service, where filesystem topology can change while the process
remains alive.

## Bounded authenticated request bodies

`lifeos serve` accepts at most 1 MiB (1,048,576 bytes) in one authenticated non-probe HTTP request.
A larger declared `Content-Length` is rejected with HTTP 413 before the request body is read. For
streamed or chunked requests, the service counts bytes itself and returns 413 before MCP dispatch
as soon as the same limit is exceeded. The downstream MCP application receives a request only
after the complete body has been collected within this bound.

The limit applies to proposal-building tool arguments as part of the same MCP JSON request, so one
remote request cannot create an unbounded proposal payload in memory or on disk. Repeated abusive
requests are an operator/network abuse concern and should additionally be controlled at the VPN,
reverse proxy, or host firewall boundary when untrusted principals share access.

`/healthz` and authenticated `/readyz` are service probes handled before MCP-body collection and do
not require proposal-sized request bodies.

## Linux requirement

The current home-node implementation binds SQLite registry access through pinned directory and
file descriptors using Linux `/proc/self/fd`. `lifeos serve` therefore fails closed at startup when
that facility is unavailable. The supplied OCI/Compose deployment and the Home Assistant Yellow
Linux path satisfy this requirement.

This Linux requirement is specific to the current always-on service implementation. Canonical
Markdown remains portable and does not depend on `/proc` or SQLite.
The read-only `lifeos doctor` recovery-readiness collector is also separate: it
uses portable descriptor-relative snapshots and is supported on macOS and Linux
without `/proc`.

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

[← Previous: Cross-Device Vault Coherence](16-cross-device-vault-coherence.md) · [Manual home](README.md) · [Next: Evidence-Grounded Research →](18-evidence-grounded-research.md)
