# Safety and Ownership

## Ownership categories

### Human-owned

Agents may read but not directly overwrite journals, user interpretations, personal profiles, important wiki claims, health conclusions, goals, or purpose statements.

### Agent-managed blocks

Agents may replace only content inside valid managed markers.

### Fully generated files

A generator may replace the whole file only when ownership is recorded in the canonical Git-tracked manifest at `system/generated-ownership.json`.
For bounded ingestion updates, LifeOS may derive that replacement by changing one
exact heading while preserving the rest of the generated file. The manifest
generator and raw content hash must both match before a draft is published.

If a generated file is manually deleted, its ownership entry is not disposable.
Ingestion reports the orphan and requires an explicit restore or ownership-release
decision; registry refresh never removes the entry.

The Obsidian **Open Proposals** workspace lists each orphan with the recorded raw
SHA-256, generator identity/version, and timestamps. **Restore instructions** never
reconstruct content: the user must restore reviewed bytes that match the recorded
hash. **Create release proposal** creates a draft whose manifest deletion is shown
as a red-line diff. Applying that draft requires trusted confirmation, an absent
target, and an unchanged ownership record. Scan, startup, status, and ingestion are
read-only with respect to this reconciliation decision.

### System policy

Policy and instruction changes require explicit proposal approval.

## Minimum patch checks

- target exists
- target hash matches
- stable ID is preserved
- note type is preserved unless explicitly approved
- citations are not silently removed
- changes stay inside authorized regions
- managed markers remain valid
- source references resolve
- proposal is explicitly approved

## Personal experiment safety and ownership

Experiment protocols, observations, amendments, user annotations, conclusions,
and lineage are canonical Markdown. Managed refreshes may update only their named
blocks and require expected hashes. Runtime indexes, schedules, summaries, and
charts are disposable.

Safety policy is deterministic and user visible. LifeOS does not diagnose,
recommend prescription medication changes, encourage dangerous restriction,
deprivation, overtraining, substance misuse, self-harm, or illegal activity, or
interpret descriptive association as medical evidence. High-risk protocols are
blocked from scheduling and activation; emergency language ends the workflow with
an immediate-safety message.

Optional providers receive no linked content automatically. Protected scopes are
default deny, source selection is inspectable and bounded, and redaction may be
applied before transmission. Core experiment workflows remain local. Any result
that would change another canonical artifact becomes a proposal with exact patches,
evidence, limitations, and stale-target checks.

## Rich capture safety, privacy, and ownership

The user description, annotations, confirmations, corrections, capture links,
lifecycle, manifest metadata, and original attachment bytes are canonical.
Managed refreshes preserve human-owned Markdown and require expected hashes.
Derived extraction, OCR, transcripts, image descriptions, nutrition estimates,
visualizations, and embeddings are disposable and must retain source and
uncertainty.

Protected captures and sensitive folders default deny external processing.
Each external operation requires explicit intent and an inspectable bounded
payload preview. Attaching a file does not authorize upload, and linking does not
authorize traversal into nearby diary or health notes. Logs and telemetry omit
full attachment contents.

Meal processing does not diagnose allergies, deficiencies, intolerances, eating
disorders, or disease and does not encourage restriction, purging, dehydration,
fasting, or medication changes. Exercise processing does not diagnose injury or
prescribe treatment and stops ordinary enrichment for urgent symptom language.
External changes generated from a capture remain proposals until separately
reviewed, approved, and applied.
