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
| `capture.split`, `capture.merge.preview`, `capture.merge.apply` | Repair mixed or duplicate captures | Merge application requires an unchanged preview fingerprint and preserves source history. |
| `capture.proposal.preview`, `capture.proposal.create` | Turn reviewed evidence into external changes | External canonical artifacts are never mutated directly. |
| `capture.privacy.preview` | Preview exact bounded local or external processing context | Protected scopes default deny; linking never authorizes neighboring-note traversal. |
| `capture.rebuild`, `capture.migration.preview`, `capture.migration.apply` | Recovery and conservative migration entry points | Implementations are deterministic and fail closed on changed sources. |

## Parameter rules

Bridge request objects reject unknown fields. Datetimes must be timezone-aware ISO 8601 strings. Mutable capture operations require the current canonical `expected_hash`. File-import paths are local inputs only; canonical records store vault-relative paths and content hashes.

## Provider neutrality

No provider identifier appears in the public capture methods or canonical schemas. Provider-backed processing is an optional adapter behind Python-owned validation, consent, redaction, timeout, and fallback boundaries.

## Visualization response

`capture.visualization.build` returns timeline points with canonical paths, counts by type and state, activity-calendar counts, processing-state counts, exercise trend points, experiment links, explicit missing-data counts, and warnings when a view is bounded. It never returns an opaque meal, exercise, or capture quality score.
