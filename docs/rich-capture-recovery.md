# Rich Capture Migration and Recovery

## Recovery boundary

Canonical recovery inputs are capture Markdown, attachment-manifest Markdown,
and original attachment bytes. Everything under `.lifeos/captures/` is derived
and may be deleted.

A rebuild discovers canonical Markdown in deterministic order using content-free
filesystem metadata, then opens and parses only the source files selected for the
current processing batch. The checkpoint stores the metadata-based source-set
fingerprint, next source position, partial index entries, and diagnostics. A later
bounded invocation resumes only when the current canonical source paths and file
identity/version metadata still match that fingerprint. Processed entries retain
their canonical content hashes; the metadata scan is discovery/invalidating work,
not a replacement source of truth.

This distinction is intentional: discovery still walks the applicable path set so
additions, moves, deletions, and ordinary file edits invalidate stale progress, but
it does not open and hash every Markdown file before honoring `interrupt_after`.
Actual Markdown byte reads and parsing are bounded to the current invocation's
source-processing budget.

If canonical Markdown is edited, added, moved, or deleted between invocations, the stale
checkpoint is discarded and the rebuild starts fresh from the current source set. A
missing, truncated, corrupt, or unsupported checkpoint is handled the same way. Runtime
checkpoint state never repairs or overrides canonical Markdown, attachment manifests, or
original bytes.

A complete rebuild reports malformed or unsupported artifacts, duplicate stable
identities, moved capture paths, missing manifests, missing or changed originals, stale
extraction, orphan manifests, and orphan originals. Where a capture reference and
unchanged original bytes contain enough evidence, a missing manifest may be rebuilt
without changing the capture or original file.

Interrupted rebuilds leave a disposable checkpoint and can be resumed while sources are
unchanged. The public recovery path returns the interrupted index immediately; manifest
reconstruction and the broader capture/attachment audit are deferred until the index
rebuild reaches a non-interrupted state. Completion publishes the same sorted index and
diagnostics as a fresh rebuild and removes the checkpoint. Rebuild and audit do not
rewrite human annotations merely to refresh derived state.

These derived index checkpoints are separate from canonical capture merge/split mutation
recovery records under `.lifeos/capture-mutations/`. Deleting `.lifeos/captures/` may
remove rebuild progress and derived indexes, but it does not authorize discarding an
active canonical-mutation recovery record.

## Attachment changes

Attachment integrity is evaluated against the canonical SHA-256 hash. A missing
file is `missing`; different bytes are `changed`. Either state invalidates
extraction, previews, transcripts, descriptions, and embeddings. Recovery never
silently replaces the expected hash with the new bytes. The user must deliberately
review and import or relink the changed file.

## Migration finding

Repository inspection found no defined legacy meal, workout, capture, or
attachment format that could be migrated safely. Direction 7 therefore ships an
audited `not-required` migration path. It rejects invented legacy sources and
records the no-op result under runtime state.

A future supported migration must begin with a preview, preserve every source,
use stable source hashes, retain timestamps, links, and human annotations, avoid
duplicate migration, resume from an audit trail, and fail closed when source bytes
change.

## Operator commands

Use the Obsidian recovery surface or the `capture.rebuild`,
`capture.migration.preview`, and `capture.migration.apply` bridge operations. The
release validator also exercises full runtime deletion and reconstruction.
