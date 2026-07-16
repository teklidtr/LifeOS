[← First-Class Reviews](10-first-class-reviews.md) · [Manual home](README.md) · [Personal Experiments →](12-personal-experiments.md)

# Semantic Retrieval and Knowledge Conversations

LifeOS semantic retrieval adds meaning-based discovery to exact search, links,
tags, metadata, and graph navigation. It does not replace those tools. The
knowledge conversation workspace keeps the scope, ranked evidence, citations,
and answer visible together so retrieval never becomes an invisible backstage
trick.

## Canonical notes and disposable indexes

Your Markdown notes remain the source of truth. Saved conversations are also
ordinary Markdown under:

```text
conversations/YYYY/<title>-<conversation-id>.md
```

The retrieval database, structural chunks, embeddings, ranking state, rebuild
journals, and caches live under `.lifeos/retrieval/`. They are derived data. You
may delete them and rebuild from the vault without losing notes, annotations,
conversation history, citations, branches, or proposal lineage.

LifeOS does not add retrieval-only fields to canonical notes. A durable note
`id`, when already present, helps preserve identity across moves. Notes without
one still receive deterministic derived identities.

## Build and inspect the index

Open **Knowledge Conversation** from the ribbon or command palette. The index
status appears before a query is sent:

- **Healthy:** the active index matches the canonical vault.
- **Stale:** notes changed after the latest synchronization.
- **Missing:** no active retrieval index exists.
- **Interrupted:** a staged rebuild can be resumed safely.
- **Corrupt or incompatible:** disposable state must be discarded and rebuilt.

Choose **Rebuild index** for a complete structural rebuild or **Synchronize
index** after ordinary creates, edits, renames, moves, and deletions. Rebuilds
write to a staging database and publish it only after completion. Cancelling or
closing Obsidian cannot replace a healthy active index with a partial one.

Chunking follows headings, explicit Obsidian block identities, and paragraph
boundaries before using a bounded fallback. Evidence cards therefore link to an
exact note, heading, and line range rather than an arbitrary slice of text.

## Choose the retrieval scope first

A conversation can begin from the ribbon, command palette, active note,
selected text, folder, tag, search result, or a saved scope. Inspect the scope
before asking. It may include or filter by:

- exact note paths or folders;
- note type, tags, source metadata, and date range;
- pinned sources and explicit exclusions;
- a selected subset instead of the whole knowledge vault;
- optional link and Graphify relationship hints.

Protected folders are denied before candidate generation. Selecting a protected
path does not override policy by itself. The workspace displays omissions and
the reason for each denial.

## How hybrid ranking works

LifeOS builds one explainable ranking from several separate signals:

1. exact phrase and lexical matches;
2. optional semantic similarity from current embeddings;
3. metadata and selected-scope relevance;
4. direct note links and bounded graph hints;
5. explicit source pins and exclusions;
6. optional provider-neutral reranking.

Every evidence card shows the contributing signals. Duplicate passages are
collapsed while preserving alternate source paths. Equal scores use a stable
path, heading, line, and chunk-identity order, so repeated queries do not shuffle
arbitrarily. Result count and total evidence characters are bounded.

When no embedding provider is configured, exact, lexical, metadata, link, and
graph retrieval still work. The workspace remains useful in local-only mode.

## Read evidence before the answer

Retrieved passages appear before or beside generated interpretation. Open any
source directly in Obsidian, inspect its section, pin it, or exclude it and run
the query again. Evidence-only mode saves the retrieved passages and citations
without asking a generation provider for an answer.

Generated paragraphs label their relationship to evidence:

- **Direct:** the cited passage explicitly supports the statement.
- **Synthesis:** the statement combines multiple cited passages.
- **Inference:** the statement is a bounded interpretation rather than a quoted fact.

A deterministic validator rejects unknown evidence IDs, nonexistent notes,
missing headings, malformed answer schemas, and unsupported citations. When the
vault does not contain enough evidence, LifeOS records a no-answer state instead
of filling the gap confidently.

## Citations and stale evidence

Saved evidence includes the note path, heading, line range, source hash, chunk
hash, excerpt, and ranking components. On resume, LifeOS compares those
fingerprints with current Markdown. A changed or deleted source is marked
**stale evidence**. The historical answer remains visible, but it is no longer
presented as current support.

Reload or rerun retrieval to create a new grounded turn. LifeOS never rewrites an
old answer to disguise changed evidence.

## Continue, branch, and revisit

Follow-up questions retain the selected scope and provenance. You may pin useful
sources, exclude irrelevant ones, refine filters, rename the conversation,
archive it, or branch from any saved turn. A branch records its parent
conversation and source turn while preserving the copied evidence history.

The managed conversation block contains query, evidence, answer, citations,
diagnostics, and provider disclosure. The **Annotations** section is
human-owned and preserved during managed updates.

## Turn an answer into knowledge

Choose a reviewed action such as:

- create a capture or draft note;
- append a proposed section;
- suggest links or research questions;
- extract claims or insights;
- create flashcard candidates;
- mark a contradiction or unresolved question.

LifeOS shows the target path, exact patch or proposed file, target content hash,
and source evidence before publishing a draft proposal. The target note remains
unchanged until the normal submit, approve, and apply lifecycle succeeds. A
changed target fails the stale check rather than accepting an outdated patch.

## Privacy and provider disclosure

Policy enforcement occurs before retrieval and again before any external
provider call. The disclosure panel lists exactly which note sections and how
many characters would be sent, whether the adapter is local or external, and
whether the request is allowed. Sensitive content is not included merely
because it is semantically similar.

Provider adapters expose capabilities through neutral embedding, reranking, and
generation contracts. Provider names and model-specific fields are not stored in
canonical conversation schemas. Disabling generation leaves local retrieval and
evidence-only conversations available.

## Degraded states and recovery

The workspace names failure states rather than presenting a blank chat panel:

- **No results:** broaden or correct the scope, or use exact search.
- **Unavailable provider:** continue with local retrieval or evidence-only mode.
- **Timeout or cancelled:** retry with the same bounded scope.
- **Malformed response:** no unsupported answer is saved as grounded fact.
- **Stale index:** synchronize changed notes.
- **Interrupted rebuild:** resume the staging rebuild.
- **Corrupt or incompatible index:** discard only `.lifeos/retrieval/` and rebuild.
- **Unsupported conversation schema:** open the Markdown artifact and use a compatible LifeOS version.

Recovery never edits canonical notes. After deleting all `.lifeos/` state, saved
conversation Markdown still opens normally and a fresh index can be built from
the vault.

## Keyboard and accessibility behavior

The workspace uses ordinary focusable controls and labelled status regions.
Use the command palette to open it without the ribbon, Tab and Shift+Tab to move
through scope, evidence, and answer controls, Enter or Space to activate a
focused action, and Escape to close transient dialogs. Evidence links remain
normal Obsidian links, and state changes are expressed in text rather than color
alone.

## Current limitations

The graphical workspace is desktop-first. Semantic quality depends on the
configured embedding adapter and the canonical notes available in the selected
scope. Graph hints improve discovery but never replace opening and citing the
source note. LifeOS does not store hidden reasoning or claim that retrieval
proves a conclusion beyond the displayed evidence.

[← First-Class Reviews](10-first-class-reviews.md) · [Manual home](README.md) · [Personal Experiments →](12-personal-experiments.md)
