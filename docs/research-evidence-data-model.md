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

## Evidence body

The external evidence text is stored inside the managed research-evidence markers in the
Markdown body. It is not agent-authored synthesis. Loading the artifact recomputes
`snapshot_hash`; mismatch fails closed.

Acquisition metadata may grow without changing evidence bytes. Changed source bytes create a new
snapshot artifact instead of replacing the prior one.

## End-to-end lineage

Normal ingestion proposal provenance records the canonical raw research `source_path` and its
full file hash. The raw artifact then resolves to `snapshot_hash` and acquisition lineage. This
keeps durable proposal/wiki lineage connected to the exact external evidence snapshot and, where
available, the query/conversation and research reason that caused collection.
