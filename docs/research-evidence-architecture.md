# Evidence-Grounded Research Architecture

## Purpose

LifeOS research starts from canonical knowledge already in the vault. External research is an
agent capability, not a LifeOS core capability. LifeOS therefore supplies a read-only context
boundary, a narrow external-evidence capture boundary, and the existing ingestion/proposal
boundary rather than embedding a browser, crawler, search provider, or second answer engine.

The invariant is:

> External evidence preserves both where it came from and why LifeOS acquired it.

## End-to-end flow

```text
user query
  -> research_query_context
       -> existing vault_context
       -> existing wiki_search
       -> no canonical write
  -> external agent judges evidence sufficiency
       -> sufficient: answer, zero write
       -> material gap: research externally
  -> research_capture_evidence
       -> canonical raw/research snapshot
       -> server-authoritative capture actor
       -> acquisition reason/query or conversation lineage
  -> external agent judges durable novelty
       -> no reusable delta: zero proposal
       -> reusable delta:
            research_create_wiki_proposal
              -> exact source_path + acquisition_id selection
              -> normal registry preflight
              -> research artifact revalidation
              -> existing proposal provenance/ownership/stale-target rules
              -> reviewed draft proposal
  -> normal explicit proposal lifecycle
```

`research_query_context` composes the established Context Pack and durable-wiki lexical search
surfaces. It deliberately does not save a conversation, answer, raw artifact, or proposal.
Knowledge conversations remain available when the user wants a durable conversation artifact,
but asking a research question does not itself create one.

## Authority boundary

The external agent owns semantic decisions:

- whether existing evidence is sufficient;
- whether an evidence gap is material;
- which external source passages are worth capturing;
- whether research produced a reusable comparison, connection, synthesis, contradiction, or
  other durable delta;
- which captured acquisition actually grounded the durable synthesis.

LifeOS owns deterministic boundaries:

- safe query/context retrieval;
- canonical external-evidence persistence;
- snapshot and metadata hashing;
- capture actor attribution;
- acquisition-lineage identity and deduplication;
- registry preflight and source hash verification;
- research-artifact revalidation before durable synthesis;
- proposal provenance, generated ownership, stale-target validation, review snapshots, and
  application.

External evidence never authorizes a wiki mutation by itself.

## Research evidence capture

`research_capture_evidence` accepts selected evidence text plus source identity metadata and
research lineage. It does not fetch the source. The MCP schema intentionally has no
`captured_by` field. Local STDIO uses the trusted configured local actor; authenticated service
requests use the request-scoped authenticated actor.

The canonical artifact lives under:

```text
raw/research/<source-identity-prefix>/<snapshot-hash-prefix>.md
```

The source identity is deterministic. A source locator such as URL or DOI is preferred. When no
locator exists, source title/author/publisher form the deterministic identity basis.

The snapshot hash is SHA-256 over the captured evidence text. The path and artifact ID bind both
source identity and snapshot hash. Loading a research artifact recomputes the snapshot hash and
fails closed if the evidence body changed.

The artifact also stores `metadata_hash` over canonical source metadata and acquisition lineage.
Loading recomputes source identity, every acquisition ID, first-capture attribution, UTC timestamp
validity, and the metadata hash. Direct edits or synchronization changes therefore cannot become
trusted lineage merely because a registry refresh observed the new full-file hash.

## Deduplication and history

Re-acquiring the same source snapshot does not create a second raw artifact. Acquisition lineage
is keyed independently from capture time using the trusted actor, origin kind/reference,
research reason, and agent-authored research context.

Therefore:

- identical snapshot + identical acquisition is a no-op;
- identical snapshot + distinct acquisition reason adds one lineage record;
- changed source content produces a distinct historical snapshot artifact;
- evidence bytes are never silently replaced while adding lineage.

Conflicting source metadata is rejected rather than silently rewriting canonical source
identity. A future controlled metadata-correction operation may amend metadata without replacing
snapshot bytes.

## Authorship, attribution, and ownership

These concepts remain separate:

- `source_author` / `source_publisher`: authorship of the external source;
- `captured_by`: trusted LifeOS actor that caused the evidence to be persisted;
- generated ownership: existing LifeOS authorization for generated canonical targets.

Capture attribution does not grant ownership of external claims and does not authorize generated
wiki content.

## Ingestion and provenance

A captured research artifact is ordinary canonical Markdown under `raw/`, so the existing
scanner and registry discover it. Research synthesis does not trust the refreshed registry hash
alone. `research_create_wiki_proposal` requires the exact `source_path` and `acquisition_id`
returned by capture, runs normal external-policy-scoped registry preflight, then reloads the
research artifact through `ResearchEvidenceService` before normal ingestion accepts it.

The reload rechecks snapshot bytes, source/metadata identity, attribution, acquisition records,
and metadata integrity. The selected acquisition must exist in that exact artifact. Generic
ingestion proposal tools do not silently select an acquisition for a `raw/research/` source.

Research-backed generated wiki provenance records:

```text
raw source path
+ canonical full-file hash
+ selected acquisition_id
```

The raw artifact then resolves the selected acquisition to the immutable snapshot and its
originating query/conversation/research reason. The resulting trace is:

```text
proposal/wiki provenance
  -> raw research path + canonical file hash + acquisition_id
  -> immutable snapshot hash
  -> exact acquisition record
  -> query/conversation reference + research reason
```

No direct web-to-wiki path exists.

## Durable novelty

LifeOS does not deterministically pretend to understand semantic novelty. The external agent must
inspect existing durable knowledge before proposing changes. The contract makes zero-write
outcomes first-class:

- existing answer is sufficient: no raw capture and no proposal;
- external evidence confirms existing durable knowledge: raw capture may exist, proposal may be
  zero;
- external evidence yields a reusable durable delta: the agent may create a reviewed draft with
  `research_create_wiki_proposal` using the exact acquisition that grounded the synthesis.

The existing ingestion/proposal engine remains the sole durable knowledge-mutation path. The
research-specific MCP tool is a narrow adapter that selects and validates research lineage before
calling that existing engine; it is not a second proposal implementation.

## Security and privacy

Research capture is a narrow canonical mutation capability, not a generic file-write surface.
There is still no MCP `write_file`, `delete_file`, move, shell, browser, or crawler capability.

Request-scoped actor identity is supplied by the trusted MCP runtime rather than client input.
Captured content is untrusted external text and remains evidence until an explicit reviewed
proposal turns a grounded synthesis into durable LifeOS knowledge. Registry refresh cannot bless
a tampered research artifact because ingestion independently reloads and verifies the capture
contract before proposal construction.
