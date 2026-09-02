# Rich capture bridge protocol

Rich capture is exposed through additive, capability-discovered JSON-RPC methods. The desktop protocol version remains backward compatible because existing method schemas are unchanged and clients must inspect `system.handshake.capabilities` before enabling a surface.

## Canonical operations

| Capability | Purpose | Safety boundary |
| --- | --- | --- |
| `capture.create`, `capture.read`, `capture.update`, `capture.transition` | Create and edit canonical Markdown capture records | Every update carries an `expected_hash`; human-owned Markdown is preserved by Python services. |
| `capture.list`, `capture.filter`, `capture.visualization.build` | Rebuildable browsing, filtered queues, and bounded inspectable chart models | Reads canonical artifacts rather than a plugin-owned database; unknown values remain missing instead of zero. |
| `capture.attachment.add`, `capture.attachment.remove`, `capture.attachment.audit` | Import original bytes, manage references, and detect missing or changed files | Imports are content-hashed and vault-relative; removing a reference never silently deletes original bytes. |
| `capture.enrichment.start`, `capture.enrichment.run`, `capture.enrichment.cancel`, `capture.enrichment.retry` | Represent resumable local extraction work | Capture is saved first; processing state is derived and recoverable. |
| `capture.inference.decide` | Confirm, reject, or correct a suggested field | Source and confidence remain visible after confirmation. |
| `capture.link`, `capture.unlink` | Link captures to LifeOS artifacts | Relationships are explicit and stale-write protected. |
| `capture.split`, `capture.merge.preview`, `capture.merge.apply` | Repair mixed or duplicate captures | A server-bound preview/source fingerprint, optimistic source hashes, idempotency key, and recoverable file-set transaction protect every output and source archive. |
| `capture.proposal.preview`, `capture.proposal.create` | Turn reviewed evidence into external changes | External canonical artifacts are never mutated directly. |
| `capture.privacy.preview` | Preview exact bounded local or external processing context | Protected scopes default deny; linking never authorizes neighboring-note traversal. |
| `capture.rebuild`, `capture.migration.preview`, `capture.migration.apply` | Recovery and conservative migration entry points | Implementations are deterministic and fail closed on changed sources. |

## Parameter rules

Bridge request objects reject unknown fields. Datetimes must be timezone-aware ISO 8601 strings.
Mutable capture operations require the current canonical `expected_hash`. File-import paths are
local inputs only; canonical records store vault-relative paths and content hashes.

The capture-mutation lineage namespace is internal to the Python transaction engine. Public
`capture.create` calls reject `source_entry_point` values beginning with `capture-mutation:` or
`capture-mutation-source:`, and public `capture.transition` calls reject the archive-lineage reasons
`merged into ...` and `split into ...`. Rejection uses the typed `reserved_capture_lineage` error
before a canonical write. Internal merge/split preparation may still write those values. Existing
canonical Markdown remains readable, but reserved-looking text never proves a completed mutation by
itself; retry success still requires the complete bilateral canonical lineage described below.

`capture.merge.preview` returns a `fingerprint` over the exact ordered source paths and hashes,
title, type, attachment IDs, link paths, and warnings. `capture.merge.apply` recomputes those fields
from canonical sources and rejects both stale sources and altered preview fields. `capture.split`
requires at least two non-empty groups and rejects duplicate or unknown attachment assignments.

`capture.merge.apply` and `capture.split` accept an additive `idempotency_key`. Keys use 1–128
lowercase letters, digits, dots, underscores, or hyphens. An identical retry returns the original
result paths; reuse for different input fails. Older clients may omit the field, in which case
Python derives a request-bound compatibility key. Active recovery state is resolved or reported as
`recovery_required` before either operation begins. Cached result receipts never authorize success
by themselves: Python reconciles the complete output markers, result lineage, source pre-mutation
hash provenance, and archive events in canonical Markdown before returning an earlier result.

## Provider neutrality

No provider identifier appears in the public capture methods or canonical schemas. Provider-backed processing is an optional adapter behind Python-owned validation, consent, redaction, timeout, and fallback boundaries.

## Visualization response

`capture.visualization.build` returns timeline points with canonical paths, counts by type and state, activity-calendar counts, processing-state counts, exercise trend points, experiment links, explicit missing-data counts, and warnings when a view is bounded. It never returns an opaque meal, exercise, or capture quality score.