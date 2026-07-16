# Rich Capture Migration and Recovery

## Recovery boundary

Canonical recovery inputs are capture Markdown, attachment-manifest Markdown,
and original attachment bytes. Everything under `.lifeos/captures/` is derived
and may be deleted.

A rebuild scans canonical captures in bounded batches, checkpoints progress, and
publishes a derived index. It reports malformed or unsupported artifacts,
duplicate stable identities, moved capture paths, missing manifests, missing or
changed originals, stale extraction, orphan manifests, and orphan originals.
Where a capture reference and unchanged original bytes contain enough evidence,
a missing manifest may be rebuilt without changing the capture or original file.

Interrupted rebuilds leave a checkpoint and can be resumed. Rebuild and audit do
not rewrite human annotations merely to refresh derived state.

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
