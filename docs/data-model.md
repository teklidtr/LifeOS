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
