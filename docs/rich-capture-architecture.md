# Rich Capture Architecture

## Status

Direction 7 adds fast, portable capture for meals, exercise, and arbitrary attachments while preserving Markdown and original bytes as the durable record.

## Product boundary

Rich capture records what happened and what evidence was supplied. It is not a second diary, habit, metric, experiment, or task system. Captures link to those artifacts and use proposals for consequential mutations outside the capture itself.

The feature is useful without a model. Local capture, hashing, deduplication, deterministic metadata and text extraction, linking, reviews, retrieval, rebuild, and proposals remain available when provider-backed enrichment is unavailable.

## Canonical layout

```text
captures/
  YYYY/
    <title>-cap-<stable-id>.md
attachments/
  originals/
    <sha256-prefix>/<sha256>/<safe-original-name>
  manifests/
    <attachment-id>.md
.lifeos/captures/
  indexes/
  extracted/
  previews/
  embeddings/
  journals/
```

Capture Markdown and attachment-manifest Markdown are canonical. Original attachment bytes are canonical evidence. Thumbnails, extracted text, OCR, transcripts, descriptions, nutrition estimates, embeddings, galleries, and indexes are derived and rebuildable.

## Ownership

| Content | Authority |
|---|---|
| User description, annotations, confirmations, corrections | Human-owned capture Markdown |
| Capture lifecycle, links, provenance, attachment references | Canonical capture Markdown |
| Attachment identity, hash, size, media type, canonical path | Canonical manifest Markdown plus original bytes |
| OCR, transcript, image description, estimated nutrition, parsed exercise | Derived result with visible provenance until confirmed |
| Changes to tasks, plans, habits, goals, notes, reminders, or calendars | Existing proposal lifecycle |
| Galleries, timelines, indexes, previews, embeddings | Disposable runtime state |

Managed blocks are named and versioned. Refreshes preserve human-owned sections and use optimistic hashes.

## Capture lifecycle

`captured -> processing -> needs-review -> enriched -> linked -> completed -> archived`

`failed` is recoverable through retry. Captures may be archived from any non-processing state. Invalid transitions fail closed with the allowed targets. Processing is represented as resumable jobs; capture persistence never waits for enrichment.

## Attachment identity and storage

The content hash is SHA-256 over original bytes. Exact duplicate bytes reuse one canonical original unless the user requests an independent copy. Same-name different-content files receive different content-addressed paths. Manifests keep stable attachment IDs, references, lineage, processing state, redaction state, and provider disclosures.

All canonical paths are vault-relative and collision safe. Absolute paths, base64 binaries, and provider names are excluded from public schemas. File reads and extraction are bounded; hashing streams. Missing, moved, renamed, or changed files produce explicit audit states and make dependent derivatives stale.

## Meal and exercise semantics

A meal may be only a sentence or photo. Nutrition is optional. Values preserve their source class: user entered, label derived, database derived, recipe calculated, image estimate, model estimate, or unknown. Estimates may use ranges and confidence categories and never become confirmed facts without user action.

An exercise capture preserves the difference between planned, performed, partial, skipped, modified, imported, and inferred activity. A scheduled time passing never marks a plan complete. Pain and danger-signal text produces conservative safety messages, not diagnosis or treatment.

## Extraction and enrichment

Local deterministic adapters support text, Markdown, bounded PDF text when a compatible local parser is present, and basic media metadata. OCR, transcription, image interpretation, nutrition estimation, and other enrichment use provider-neutral contracts with cancellation, timeout, schema validation, disclosure, redaction, and deterministic test adapters.

Extracted text is stored separately from original files and records method, version, source locator, quality, and source hash. Changed bytes invalidate extraction and embeddings.

## Privacy

Protected scopes default deny external processing and semantic indexing. Each provider operation previews the exact attachment metadata and bounded text or file scope to be disclosed. Linking does not authorize traversal into neighboring diary, health, or private notes. Logs contain identifiers, sizes, and status codes, not full attachment contents.

## Retrieval, conversations, reviews, and experiments

Only approved textual representations and metadata enter retrieval. Results cite the capture, attachment, representation kind, source hash, and stale state. Knowledge conversations distinguish original user text from OCR, transcript, and AI-derived description.

Daily and weekly reviews surface dismissible evidence-fingerprinted capture findings. Personal experiments may link captures as observations or supporting evidence, but inferred values require explicit mapping and confirmation before becoming measurements.

## Recovery and migration

Indexes, manifests, previews, extractions, embeddings, timelines, and galleries can be rebuilt from capture Markdown, manifest Markdown, and original files. Rebuilds checkpoint progress and never rewrite human sections unnecessarily. Legacy migration is conservative, source-hash guarded, resumable, and a documented no-op when no supported legacy form is found.

## Obsidian workspace

The plugin is a thin typed client with quick-capture and full-review modes. Entry points include ribbon, command palette, active note, selected text, clipboard, paste, drag and drop, reviews, experiments, and knowledge conversations. Explicit accessible states cover empty, duplicate, unsupported, oversized, missing, changed, processing, provider unavailable, protected, stale, conflict, migration, and rebuild conditions.

## Sequenced implementation

| Task | Capability |
|---|---|
| LIFEOS-1600 | Architecture, dependency audit, and task design |
| LIFEOS-1601 | Canonical capture and attachment artifacts |
| LIFEOS-1602 | Storage, lifecycle, extraction, and resumable processing |
| LIFEOS-1603 | Meal, exercise, enrichment, and safety contracts |
| LIFEOS-1604 | Retrieval, conversation, review, experiment, and proposal integration |
| LIFEOS-1605 | Bridge protocol and application service |
| LIFEOS-1606 | Obsidian rich-capture workspace and accessible entry points |
| LIFEOS-1607 | Migration, privacy, recovery, performance, and fixtures |
| LIFEOS-1608 | Documentation, validation, reports, and release packaging |

## Schema compatibility

Direction 7 uses capture schema version 1, attachment-manifest schema version 1, enrichment schema version 1, and derived-index schema version 1. Unsupported canonical versions fail closed. Derived version mismatches require rebuild rather than canonical mutation.
