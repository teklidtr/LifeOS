# Semantic Retrieval and Knowledge Conversation Architecture

## Status

Shipped in Phase 14 through `LIFEOS-1400` to `LIFEOS-1411`.

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

## Compatibility with ingestion and Graphify

Ingestion provenance and original-source immutability remain unchanged. Retrieved
chunks retain source metadata but do not become source records. Graphify may add a
bounded relationship signal; original notes must still be opened and cited. Index
rebuilds read canonical post-ingestion notes and do not invoke ingestion or mutate
Graphify state.

## Performance and recovery

Large-vault behavior uses bounded file batches, bounded embedding batches,
streaming SQLite writes, cancellation checkpoints, progress notifications, and
context budgets. A staging rebuild may resume after interruption. The active index
stays readable until publication. Incremental synchronization is idempotent and
can fall back to a full rebuild after incompatible schema or corruption.

## Privacy and removal

Built-in protected prefixes and optional `system/retrieval-policy.yml` exclusions
are enforced before indexing and retrieval. Policy parsing fails closed. Removing
the plugin or deleting derived state leaves ordinary Markdown conversations and
notes readable. No provider credentials or provider-specific model fields are
stored in canonical artifacts.

## Sequenced implementation

Phase 14 is decomposed into `LIFEOS-1400` through `LIFEOS-1411`: architecture,
contracts, structural index, synchronization, hybrid retrieval, conversation
artifacts, grounding, proposals, bridge, Obsidian workspace, recovery/privacy, and
release validation.
