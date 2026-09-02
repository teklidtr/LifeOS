# Semantic Retrieval and Knowledge Conversation Architecture

## Status

Shipped in Phase 14 through `LIFEOS-1400` to `LIFEOS-1411`, with the existing
Context Pack surface converged onto the same retrieval subsystem in Phase 16 by
`LIFEOS-1642`.

## Purpose

Direction 5 adds an inspectable retrieval layer and an Obsidian-native knowledge
conversation workspace without replacing exact search, links, tags, metadata,
Graphify, or ordinary note navigation. Canonical Markdown remains authoritative.

## Existing capability audit

LifeOS already provides token-aware lexical search, structural Markdown parsing,
symlink-safe vault traversal, disposable SQLite registries, optional Graphify
views, provider-neutral model seams, proposal-gated consequential edits, a
versioned JSON-RPC bridge, and UI-first Obsidian workspaces. The new capability
therefore composes these boundaries rather than creating a second knowledge
system.

No existing module provides structural chunk provenance, vector storage, hybrid
ranking, canonical conversation artifacts, deterministic claim citations, or a
conversation-to-proposal workflow. These are new responsibilities.

## Product invariants

- Markdown notes and conversation artifacts are canonical and portable.
- Indexes, chunks, embeddings, caches, ranking state, and rebuild journals are derived.
- Exact, lexical, metadata, link, and graph retrieval work without a model provider.
- Provider-specific names never enter canonical schemas or public contracts.
- Protected scopes are denied before candidate generation and before provider calls.
- Evidence and ranking explanations remain visible beside generated interpretation.
- A generated answer cannot cite a path, section, or evidence item that validation
  did not independently resolve.
- Conversation outcomes can create proposals, never silent note mutations.

## Canonical layout

```text
conversations/<year>/<slug>-<conversation-id>.md
system/retrieval-policy.yml                 # optional user-authored policy
```

A conversation stores stable identity, schema version, title, timestamps,
lifecycle, selected scope, branch lineage, pinned and excluded sources, and
turn-level evidence/citation metadata. Managed turn rendering is separated from
human-owned annotations. Human text outside managed blocks is preserved byte for
byte during managed updates.

## Derived layout

```text
.lifeos/retrieval/index.sqlite3
.lifeos/retrieval/index.sqlite3.rebuild
.lifeos/retrieval/rebuild-state.json
.lifeos/retrieval/health.json
```

The active index is replaced only after a complete staging rebuild. Interrupted
staging rebuilds are resumable and never invalidate a healthy active index.
Deleting `.lifeos/retrieval/` loses no canonical knowledge or conversation state.

## Structural chunking and identity

Markdown is split by headings and explicit Obsidian block identifiers before a
bounded paragraph fallback is used. Chunks preserve path, document identity,
heading path, line range, block identity, outbound links, frontmatter metadata,
source hash, normalized-content hash, and chunk hash.

A durable note `id` is the preferred document identity. Notes without one receive
a deterministic path identity. Incremental rename detection preserves the prior
identity when content or a durable `id` proves continuity. Chunk identities combine
document identity, structural position, and normalized content fingerprint so
unrelated edits do not renumber every chunk.

## Index schema and lifecycle

The versioned SQLite schema contains documents, chunks, links, embeddings, and
metadata. Embeddings are keyed by chunk hash plus provider capability key and model
key. A changed chunk makes the old embedding stale rather than authoritative.

Supported lifecycle operations:

1. inspect health and schema compatibility;
2. start or resume a bounded staging rebuild;
3. incrementally synchronize create, edit, rename, move, and delete events;
4. atomically publish a complete rebuild;
5. discard and recreate incompatible or corrupt derived state.

Malformed Markdown, unsupported files, unsafe paths, and protected scopes are
reported as diagnostics rather than indexed silently.

## Provider-neutral contracts

The retrieval package defines independent contracts for embedding, optional
reranking, and answer generation. Each advertises capability metadata and accepts
bounded batches, timeout, and cancellation. Deterministic fixture adapters support
regression tests. No-provider and unavailable-provider states fall back to local
lexical, metadata, link, and graph retrieval.

Only the bounded evidence selected after policy enforcement may be sent to an
external provider. The request disclosure lists paths, sections, character count,
provider mode, and whether protected content is present. Protected content is
never externally sent unless policy and an explicit per-request grant both allow it.

## Hybrid retrieval

Candidate generation composes:

- exact phrase and token-aware lexical score;
- optional cosine similarity over current embeddings;
- metadata matches and user-selected scope;
- direct and second-order note-link evidence;
- optional Graphify relationship hints treated as candidates, not facts;
- explicit pin boosts and exclusion filters.

Scores expose their components. Filters are applied before ranking. Duplicate
passages are suppressed by normalized-content fingerprint. Result count and
context budget are bounded. Equal scores are ordered deterministically by path,
heading, line, and chunk identity.

## Context Packs over hybrid retrieval

`ContextPack` and the MCP `vault_context` tool are the bounded context-management
layer over this authoritative retrieval subsystem. They do not own another vector
store, embedding abstraction, or ranking implementation. Explicit `focus_paths`
are validated and placed first; remaining source slots are filled from healthy
hybrid retrieval using the existing exact, lexical, semantic, metadata, link,
graph, deduplication, privacy, and deterministic-ordering contracts.

A Context Pack exposes only bounded retrieval provenance: source path and excerpt,
retrieval mode, contributing ranking-signal names, numeric ranking components, and
duplicate paths. This is an explanation of deterministic retrieval evidence, not
hidden model reasoning. Applicable `system/instructions.yml` rules are evaluated
after the final source set is selected and remain separate from both ranking and
mutation authority.

The retrieval index is disposable. If it is missing, stale, corrupt, incompatible,
or otherwise unavailable, Context Pack construction returns to canonical
deterministic lexical search and records the degraded capability in `omissions`
instead of treating derived state as authoritative. A healthy index without a
semantic query provider still contributes local exact/lexical, metadata, link,
graph, and pin signals and reports that semantic retrieval was not configured.
For an explicitly protected external MCP scope, Context Packs conservatively use
the canonical lexical path until the hybrid request contract itself carries
external-disclosure mode, preventing protected content from entering a local-mode
hybrid candidate/provider path.

`wiki_search` deliberately remains a separate lexical primitive. It is useful for
exact, composable durable-wiki discovery after an initial Context Pack and does
not need to become a second wrapper around hybrid retrieval merely for API
uniformity.

A Context Pack is a starting map, not a crawl or answer-generation pipeline. The
external agent remains responsible for deciding whether to continue with
`vault_list`, `vault_search`, `vault_read_markdown`, `vault_read_many`,
`vault_links`, `wiki_search`, or other bounded exploration operations. This keeps
LIFEOS-1639 composability intact and leaves interpretation outside the retrieval
engine.

## Conversation workspace

The Obsidian workspace is evidence-first, not a generic chat panel. It includes:

- a scope inspector and privacy disclosure;
- query composer and evidence-only mode;
- ranked evidence cards with score explanations and exact note/heading links;
- pin and exclude controls;
- grounded answer paragraphs with claim-level citations and support labels;
- follow-up, branch, rename, archive, resume, and open-artifact actions;
- explicit missing-index, stale-index, no-result, no-provider, timeout, cancelled,
  malformed-response, unsupported-schema, and stale-evidence states.

Ribbon and command entry points may seed the scope from the active note, selected
text, folder, tag, search result, or saved scope. The workspace remains the primary
interaction surface.

## Grounding and citation validation

The answer generator receives evidence IDs, never permission to invent source
references. Its structured result labels each paragraph as direct support,
synthesis, or inference. Deterministic validation rejects unknown evidence IDs,
nonexistent paths, missing headings, changed source hashes, and unsupported schema.

Evidence-only mode bypasses generation. When evidence is insufficient, the saved
turn records a no-answer result. On resume, current source and chunk hashes are
compared with stored fingerprints so stale evidence is visible without rewriting
history.

## Conversation to knowledge

A reviewed answer may prepare one of these proposal intents: capture, new note,
append section, link suggestion, research questions, extracted claims, flashcard
candidates, contradiction, or unresolved question. Each preview contains exact
target paths, typed patches, evidence references, target hashes, and stale-target
checks. The existing submit, approve, apply, and recovery lifecycle remains the
only route to other canonical notes.

## External research composes retrieval; it does not replace it

LIFEOS-1641 reuses this subsystem when an agent researches beyond the existing
vault. It does not add another semantic index, conversation engine, answer model,
or embedded web-search provider. `research_query_context` simply composes the
existing Context Pack and lexical durable-wiki search in MCP external-disclosure
mode. The query is read-only and is not automatically saved as a knowledge
conversation.

If the returned evidence is sufficient, the external agent may answer with zero
canonical writes. If a material evidence gap remains, the external agent performs
outside research in its own environment and submits selected evidence through the
typed `research_capture_evidence` boundary. LifeOS stores that exact snapshot as
hash-bound canonical Markdown under `raw/research/` with acquisition lineage.
Only after capture does the source participate in the ordinary registry,
retrieval, ingestion, provenance, and proposal machinery.

A captured research source is therefore an ordinary canonical evidence source for
these downstream systems, not a privileged shortcut. Retrieval may index it like
other allowed canonical Markdown after synchronization. Conversation evidence may
cite it only through the existing path/section/hash validation. Durable synthesis
still becomes an ordinary proposal, and no durable delta means no proposal. An
uncaptured external claim may not jump directly into canonical wiki evolution.

Where available, acquisition lineage retains the originating query or conversation
reference and the research reason. That lineage is distinct from the conversation
artifact itself and from generated ownership. See
[Research Evidence Architecture](research-evidence-architecture.md).

## Compatibility with ingestion and Graphify

Ingestion provenance and original-source immutability remain unchanged. Retrieved
chunks retain source metadata but do not become source records. A captured
`raw/research/` snapshot is already canonical source material, so normal ingestion
records its path and current full-file hash without a research-specific proposal
engine. Graphify may add a bounded relationship signal; original notes must still
be opened and cited. Index rebuilds read canonical post-ingestion notes and do not
invoke ingestion or mutate Graphify state.

## Performance and recovery

Large-vault behavior uses bounded file batches, bounded embedding batches,
streaming SQLite writes, cancellation checkpoints, progress notifications, and
context budgets. A staging rebuild may resume after interruption. The active index
stays readable until publication. Incremental synchronization is idempotent and
can fall back to a full rebuild after incompatible schema or corruption.

For desktop bridge calls, request IDs are registered before serialized dispatch.
`request.cancel` is the only control frame processed concurrently with ordinary
work; it signals the existing token used by index recovery/rebuild/sync, hybrid
search, and conversation answering. Cancellation acknowledgements describe only
whether the signal was accepted. The operation's own result or typed error records
whether it actually stopped. Disconnect and shutdown use the same cooperative
signal, leaving the active index readable and resumable staging intact.

## Privacy and removal

Built-in protected prefixes and optional `system/retrieval-policy.yml` exclusions
are enforced before indexing and retrieval. Policy parsing fails closed. MCP
research-query composition uses the same external-disclosure retrieval mode as
other user-facing MCP reads, including the configured node-local runtime
exclusions. Removing the plugin or deleting derived state leaves ordinary
Markdown conversations, research snapshots, and notes readable. No provider
credentials or provider-specific model fields are stored in canonical artifacts.

## Sequenced implementation

Phase 14 is decomposed into `LIFEOS-1400` through `LIFEOS-1411`: architecture,
contracts, structural index, synchronization, hybrid retrieval, conversation
artifacts, grounding, proposals, bridge, Obsidian workspace, recovery/privacy, and
release validation. `LIFEOS-1642` later reuses that shipped subsystem for the
pre-existing Context Pack/MCP context surface rather than creating a parallel RAG
layer. `LIFEOS-1641` composes those same retrieval/context capabilities with the
controlled raw-research capture boundary for externally acquired evidence.
