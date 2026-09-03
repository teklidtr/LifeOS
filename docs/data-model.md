# Initial Data Model

## Durable note

```yaml
id:
type:
title:
description:
status:
confidence:
review_reasons: []
```

## Typed relation

```yaml
target:
type:
evidence: explicit | derived | inferred | ambiguous
confidence:
source_refs: []
status: active | candidate | rejected
```

## Goal

```yaml
type: goal
id:
horizon: long-term | medium-term
status:
title:
description:
why: []
review_cadence:
```

## Plan

```yaml
type: plan
id:
goal:
status:
desired_outcome:
review_date:
```

## Embedded task

```yaml
task_id:
title:
status:
duration:
energy:
mode:
goal:
plan:
due:
blocked_by: []
```

## Metric definition

```yaml
type: metric
id:
title:
description:
value_type:
unit:
range:
aggregation:
missing_value_policy:
```

## Proposal

```yaml
proposal_id:
status: draft | pending | approved | rejected | applied | stale
target_hashes: {}
items: []
```

## Multi-source ingestion proposal grounding

Folder or explicit multi-source ingestion still creates an ordinary proposal and an ordinary
`PatchDocumentV2`; it does not introduce another canonical proposal format. The public batch call
carries the exact `(path, content_hash)` snapshots returned when the agent read the selected
evidence with `vault_read_many`. Those are observed evidence versions, not hints that a later
registry refresh may silently advance. Proposal construction succeeds only while every current
registered source still matches its supplied observation hash; a mismatch requires rereading and
reasoning from the new bytes before a new batch can be proposed.

The batch-specific review facts live in the proposal metadata extension and are included in the
normal review digest:

```yaml
extensions:
  ingestion:
    action: evolve_wiki_batch
    source_count: 3
    operation_count: 2
    source_snapshots:
      - path: notes/a.md
        content_hash: sha256:<64 lowercase hex characters>
      - path: notes/b.md
        content_hash: sha256:<64 lowercase hex characters>
      - path: notes/c.md
        content_hash: sha256:<64 lowercase hex characters>
    target_grounding:
      - target_path: wiki/alpha.md
        kind: update_sections
        headings: [Evidence, Mechanism]
        rationale: Reconcile the reviewed contributions.
        tag_rationale: Preserve the reviewed taxonomy decision when tags change.
        sources:
          - path: notes/a.md
            content_hash: sha256:<64 lowercase hex characters>
          - path: notes/b.md
            content_hash: sha256:<64 lowercase hex characters>
      - target_path: wiki/beta.md
        kind: create
        rationale: Preserve a reusable synthesis.
        sources:
          - path: notes/c.md
            content_hash: sha256:<64 lowercase hex characters>
```

`related_sources` is the deterministic ordered union of the selected batch source paths, while
`target_grounding` identifies the narrower source subset that actually supports each mutation.
When a generated create or generated-owned update includes a reviewed taxonomy rationale, that
rationale remains in the digest-bound target-grounding metadata and the human-readable proposal
body rather than being discarded after validation. Every target path occurs at most once in the
patch document. Several exact-section changes to one human-owned Markdown file are first
reconciled into one final candidate and serialized as one base-hash-bound `patch_human_file`;
generated-owned targets similarly produce one ownership/hash-bound replacement with only that
target's relevant source snapshots merged into cumulative provenance. The batch is bounded
independently by source count, target count, and the serialized patch-plus-review payload; those
limits do not change the canonical patch schema.

## Generated Wiki provenance (canonical)

LifeOS-generated Wiki pages may carry canonical page-level evidence lineage in
frontmatter:

```yaml
lifeos_provenance:
  schema_version: 1
  sources:
    - path: notes/example.md
      content_hash: sha256:<64 lowercase hex characters>
    - path: journal/2026-08-23.md
      content_hash: sha256:<64 lowercase hex characters>
  generator:
    id:
    version:
    prompt_schema_version:
    model_id:
  created_at: YYYY-MM-DDTHH:MM:SSZ
```

`sources` is a non-empty ordered list of source objects. Exact
`(path, content_hash)` repeats are deduplicated. The same path with a changed hash
is retained as another historical snapshot, so accepted evidence history is not
silently rewritten to the source's current bytes.

When a generated-owned Wiki page receives another accepted source contribution,
LifeOS preserves the existing source order, generator metadata, and provenance
`created_at`, then appends the new source snapshot when it is not an exact repeat.
Human-owned Wiki patches do not acquire generated provenance automatically.
Provenance does not grant generated-file ownership or write authority.

See [Generated Wiki Provenance](generated-wiki-provenance.md) for the full
validation and merge contract.

## Graph view state

```yaml
view_name:
status: clean | dirty | rebuilding | failed
graph_hash:
last_updated_at:
```

## Retrieval index (derived)

The retrieval index uses SQLite schema version 1 under
`.lifeos/retrieval/index.sqlite3`. It is disposable and rebuildable from Markdown.

```text
documents(document_id, path, title, note_type, source, note_date, tags,
          frontmatter, content_hash, indexed_at)
chunks(chunk_id, document_id, path, heading, heading_path, line range,
       block_id, text, normalized_hash, chunk_hash, links, token_count, metadata)
links(from_chunk_id, target_path, target_heading)
embeddings(chunk_id, adapter_key, model_key, chunk_hash, dimensions, vector,
           created_at)
```

An embedding is current only when its stored chunk hash matches the current
structural chunk. Index schema changes require rebuilding derived state, not
migrating canonical notes.

## Knowledge conversation (canonical)

```yaml
conversation_schema: 1
conversation_id:
title:
created_at:
updated_at:
status: active | archived
scope:
  paths: []
  folders: []
  note_types: []
  tags: []
  sources: []
  date_from:
  date_to:
  excluded_paths: []
  pinned_paths: []
  include_graph: true
pinned_sources: []
excluded_sources: []
parent_conversation_id:
branch_from_turn_id:
turns: []
```

Each turn stores a stable turn ID, query, lifecycle state, bounded evidence,
answer paragraphs, support labels, citations, explanation, disclosure, and
diagnostics. Evidence stores path, heading, line range, source and chunk hashes,
excerpt, ranking signals, and stale state. Hidden chain-of-thought is not stored.
The managed turn block and human-owned annotations are distinct preservation
zones.

## Research source (canonical)

Externally acquired research evidence is canonical Markdown under
`raw/research/<source-key>/<snapshot-key>.md` with `type: research-source` and
`research_schema: 1`.

```yaml
artifact_id: research-<source-prefix>-<snapshot-prefix>
source_identity: sha256:<digest>
source_locator:
source_title:
source_author:
source_publisher:
snapshot_hash: sha256:<digest>
first_captured_at:
first_captured_by:
acquisitions:
  - acquisition_id: acq-<digest-prefix>
    captured_at:
    captured_by:
    origin_kind: query | conversation | manual | other
    origin_ref:
    research_reason:
    research_context:
```

`source_author` and `source_publisher` describe the external source;
`captured_by` identifies the trusted LifeOS actor that acquired the snapshot;
neither grants generated ownership or mutation authority. The managed evidence
body is hash-bound by `snapshot_hash`. Re-capturing identical evidence reuses the
same artifact, while distinct acquisition reasons add idempotent lineage and
changed evidence bytes create a distinct historical snapshot. Normal ingestion
provenance then records the canonical raw research path and full file hash, which
can be traced back to the exact snapshot and its acquisition lineage.

See [Research Evidence Data Model](research-evidence-data-model.md) for the full
identity, immutability, and lineage contract.

## Personal experiment (canonical)

```yaml
experiment_schema: 1
experiment_id:
title:
description:
category:
state: idea | drafting | baseline | scheduled | active | paused | completed | abandoned | analyzed | archived
created_at:
updated_at:
origin:
  kind: scratch | goal | plan | task | review | conversation | capture
  path:
protocol:
  question:
  hypothesis:
  rationale:
  intervention:
  constants: []
  comparison:
  baseline_requirements:
  outcome_measures:
    - measure_id:
      display_name:
      kind: count | duration | rating | percentage | continuous | completion | qualitative
      unit:
      cadence:
      source:
      direction: increase | decrease | target | neutral
      valid_min:
      valid_max:
      missing_behavior:
      aggregation:
      role: primary | secondary | adherence | contextual
  phases:
    - phase_id:
      name:
      kind: baseline | intervention | washout
      start_date:
      end_date:
      intervention:
  adherence_expectation:
  confounders: []
  risks: []
  stop_rules: []
  success_criteria: []
  failure_criteria: []
  inconclusive_criteria: []
  schedule:
    timezone:
    cadence:
    days: []
    time:
    window_minutes:
    grace_minutes:
safety:
  level: ordinary | caution | informational-only | blocked | emergency
  explanations: []
observations: []
amendments: []
lifecycle_history: []
analyses: []
conclusion:
conclusion_notes:
follow_up_decisions: []
parent_experiment_id:
lineage: []
links: []
source_references: []
```

Every observation has a stable ID, measure and phase identity, observed timestamp,
state (`measured`, `not-measured`, `not-applicable`, `skipped`, or `unavailable`),
optional value, note, context links, source, and creation timestamp. Only measured
observations may contain values. Analyses record the exact observation IDs used,
missing-data treatment, assumptions, limitations, descriptive/inferential label,
and generated results. Protocol amendments preserve the prior protocol hash and
a dated replacement rather than rewriting the original active protocol.

Derived indexes, due windows, chart models, and analysis caches live under
`.lifeos/experiments/` and are rebuildable from these artifacts.

## Rich capture (canonical)

```yaml
id: cap-<timestamp>-<random>
type: rich-capture
schema_version: 1
title:
description:
capture_type: meal | exercise | attachment | mixed
state: captured | processing | needs-review | enriched | linked | completed | failed | archived
captured_at:
event_at:
timezone:
source_entry_point:
privacy_scope: standard | private | protected
sensitive: false
location:
tags: []
attachments: []
links: []
derived_values: []
domain_data: {}
extraction_status:
enrichment_status:
exclude_from_semantic: false
exclude_from_conversations: false
exclude_from_reviews: false
exclude_from_experiments: false
provenance: []
lifecycle: []
merged_from: []
split_from:
created_at:
updated_at:
```

The managed capture block renders inspectable summaries. Human annotations stay
outside it. Derived values retain field name, value or range, unit, source,
confidence, assumptions, evidence references, and status. `unknown` cannot carry
a numeric value, and a missing value is never normalized to zero.

## Attachment manifest (canonical)

```yaml
id: att-<stable-id>
type: attachment-manifest
schema_version: 1
content_hash: sha256:<digest>
original_filename:
canonical_path: attachments/originals/<prefix>/<digest>/<safe-name>
media_type:
byte_size:
attachment_kind: original | user-edited | generated-derivative
capture_source:
imported_at:
created_at:
modified_at:
extraction_status:
preview_status:
transcript_status:
duplicate_of:
parent_capture_ids: []
derived_artifact_refs: []
provider_disclosures: []
redaction_state:
```

Original bytes plus the manifest are canonical evidence. Extracted text, OCR,
transcripts, thumbnails, waveforms, descriptions, embeddings, and indexes are
versioned derived artifacts keyed by the original content hash.

## Personal pattern (Phase 17 proposed canonical)

Phase 17 recognizes individual reviewable working hypotheses under `patterns/`.
The exact parser and serializer ship in LIFEOS-1701; the semantic shape is fixed by
[Evidence-Backed Personal Model Architecture](personal-model-architecture.md).
Unrecognized Markdown under `patterns/` remains ordinary user content.

```yaml
pattern_schema: 1
type: pattern
id: pattern-example
title:
description:
status: seed | active | needs-review | archived
confidence: low | medium | high
review_reasons: []
statement:
origin:
  kind: manual | observation | review | conversation | experiment | goal | plan | agent
  source_ref:
created_at:
updated_at:
last_reviewed_at:
review_due_at:
evidence_fingerprint: sha256:<digest>
evidence:
  - path:
    source_id:
    content_hash: sha256:<digest>
    role: supporting | contesting | contextual
    observation_id:
    event_id:
evaluation:
  kind:
  parameters: {}
```

Stable source identity, reviewed path, and reviewed content hash remain separate
facts. Optional `source_id`, `observation_id`, and `event_id` fields are present only
when the referenced evidence has those durable identities. Historical reviewed
hashes are not silently advanced when a source changes or moves.

The evidence fingerprint is derived deterministically from normalized evidence
references and is ordering-independent. Evidence roles remain separate so
supporting material cannot erase contesting evidence. Missing evidence is unknown,
not negative evidence. `evaluation` is optional and only names a supported
deterministic re-evaluation recipe; it cannot encode an autonomous semantic model.

Machine-managed evidence summaries use validated managed blocks while human
reflection remains outside those blocks. Canonical pattern files are human-owned.
The aggregate Personal Model is derived under `.lifeos/personal-model/` and is not
a second canonical artifact or generated biography.
