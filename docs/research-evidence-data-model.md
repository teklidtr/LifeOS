# Research Evidence Data Model

## `research-source`

Externally acquired evidence is canonical Markdown under `raw/research/` with
`type: research-source` and `research_schema: 1`.

Required identity fields:

| Field | Meaning |
| --- | --- |
| `artifact_id` | Deterministic ID derived from source identity and snapshot hash |
| `source_identity` | SHA-256 identity for the external source |
| `snapshot_hash` | SHA-256 over the exact captured evidence text |
| `metadata_hash` | SHA-256 over the canonical source metadata and acquisition-lineage record |
| `source_title` | Human-readable external source title |
| `first_captured_at` | UTC timestamp of first canonical capture |
| `first_captured_by` | Trusted LifeOS actor for first capture |
| `acquisitions` | One or more acquisition-lineage records |

Optional source-authorship fields:

- `source_locator`: URL, DOI, or other stable locator;
- `source_author`: external source author;
- `source_publisher`: external publisher/organization.

These fields describe the external source. They are not LifeOS generated-ownership
authorization.

## Acquisition lineage

Each acquisition contains:

| Field | Meaning |
| --- | --- |
| `acquisition_id` | Deterministic acquisition-lineage ID |
| `captured_at` | UTC timestamp when this lineage record was first added |
| `captured_by` | Server-authoritative LifeOS actor |
| `origin_kind` | `query`, `conversation`, `manual`, or `other` |
| `origin_ref` | Optional query/conversation reference |
| `research_reason` | Concise evidence gap/question that caused acquisition |
| `research_context` | Optional agent-authored context, kept distinct from evidence text |

`acquisition_id` excludes capture time so an identical repeated acquisition is idempotent.
Loading an artifact recomputes each acquisition ID from the actor/origin/reason/context fields,
requires `first_captured_at` and `first_captured_by` to match the first acquisition, and verifies
`metadata_hash`. Capture timestamps and other metadata therefore cannot be changed silently
without invalidating the canonical capture record.

## Evidence body

The external evidence text is stored inside the managed research-evidence markers in the
Markdown body. It is not agent-authored synthesis. Loading the artifact recomputes
`snapshot_hash`; mismatch fails closed.

Acquisition metadata may grow without changing evidence bytes. Changed source bytes create a new
snapshot artifact instead of replacing the prior one.

## End-to-end lineage

Durable research synthesis must select one exact acquisition. `research_create_wiki_proposal`
accepts the captured `source_path` plus the selected `acquisition_id`, runs normal registry
preflight, reloads and validates the research artifact, and rejects a missing or mismatched
acquisition. Generic ingestion does not choose a research acquisition implicitly.

For research-backed generated wiki content, `lifeos_provenance.sources[]` retains the canonical
raw research `path`, full file `content_hash`, and selected `acquisition_id`. The raw artifact then
resolves that acquisition to its snapshot, actor, query/conversation reference, and
`research_reason`.

This creates an unambiguous chain:

```text
proposal/wiki provenance
  -> raw research path + canonical file hash + selected acquisition_id
  -> immutable snapshot hash
  -> exact acquisition record
  -> query/conversation reference + research reason
```
