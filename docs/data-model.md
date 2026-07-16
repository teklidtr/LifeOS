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
