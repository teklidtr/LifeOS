[← Previous: Executive Summary & Philosophy](02-executive-summary-and-philosophy.md) · [Manual home](README.md) · [Next: Setup & Installation →](04-setup-and-installation.md)

# 3. Feature Breakdown

This chapter explains each core module in two ways:

- **What it is:** the module's purpose.
- **How it connects:** how it exchanges data or authority with the rest of
  LifeOS.

## 3.1 Markdown vault

### What it is

The vault is the durable, human-readable center of LifeOS. It is an ordinary
directory of Markdown files that can be opened directly in Obsidian or any text
editor.

Canonical areas used by current features include:

```text
journal/
raw/
study/
wiki/
flashcards/
patterns/
profile/
goals/
plans/
experiments/
metrics/
reviews/
conversations/
captures/
attachments/
proposals/
system/
```

You do not need every top-level directory on day one, and the first-party
`lifeos init` bootstrap intentionally creates only its documented core roots.
Feature-owned canonical areas can appear as those features are used. `wiki/`
deliberately has no required semantic subfolders. The connected agent may keep it
flat or create useful nested folders as knowledge accumulates. Folder structure
is allowed to emerge from the vault instead of being imposed as a universal
ontology.

### How it connects

Every major LifeOS module reads from the vault:

- context search reads descriptions and note bodies;
- planning reads embedded actions from `plans/`;
- study reads cards from `flashcards/`;
- observation reads metrics and activities from `journal/`;
- graph views derive nodes and edges from canonical notes;
- exports create purpose-specific bundles from selected notes;
- proposals apply approved changes back to the vault.

## 3.2 Markdown parser and structural diagnostics

### What it is

The parser reads YAML frontmatter, note bodies, durable metadata, and
LifeOS-managed blocks.

A general durable note may use:

```yaml
---
id: wiki-energy-management
type: wiki
title: Energy Management
description: Notes about matching work to daily capacity.
status: active
confidence: medium
review_reasons:
  - New evidence
---
```

Managed regions use explicit markers:

```md
<!-- lifeos:managed:start related-sources -->
Generated material
<!-- lifeos:managed:end related-sources -->
```

### How it connects

Parser findings feed:

- structural lint;
- status diagnostics;
- context search;
- planning and study loaders;
- observation analysis;
- graph extraction;
- public-export privacy checks;
- proposal preflight validation.

Malformed YAML, duplicate fields, broken managed blocks, and invalid domain
metadata are reported rather than silently interpreted.

## 3.3 Secure vault traversal

### What it is

The vault layer provides descriptor-based, symlink-safe access to canonical
files. It prevents consumers from accidentally following links outside the
configured vault.

### How it connects

Context, graph, exports, planning, study, observation, and read-only facade tools
use the same traversal rules. This keeps cross-component behavior consistent:
a path rejected as unsafe by one module should not be trusted by another.

## 3.4 Scanner and SQLite registry

### What it is

The scanner computes deterministic file facts such as:

- vault-relative path;
- content hash;
- file size;
- deletion state;
- stable IDs.

The SQLite registry can also store derived proposal and provenance index rows,
but those indexes have their own rebuild operations. It remains disposable query
state rather than canonical knowledge.

### How it connects

The supported `lifeos scan` command and MCP `registry_refresh` operation refresh
the **file and proposal indexes**. They support:

- proposal listings and counts;
- file-change comparison;
- status reporting;
- registered-source validation for ingestion.

The registry schema also contains provenance tables used for provenance lookup.
Those rows are rebuilt separately by the deterministic provenance-index refresh;
`lifeos scan` does not implicitly refresh them.

The registry does **not** replace Markdown and should not contain the only copy of
canonical knowledge. It may be deleted and rebuilt from canonical state.

Use either supported file/proposal refresh adapter:

```bash
uv run lifeos scan
uv run lifeos scan --json
```

An MCP-connected agent uses `registry_refresh`. Neither surface rebuilds the
separate provenance, semantic retrieval, graph, or export indexes. See
[Registry](../registry.md) for the exact SQLite and refresh contracts.

## 3.5 Status and diagnostics

### What it is

The status command checks system health:

```bash
uv run lifeos status
uv run lifeos status --json
```

It distinguishes conditions including:

- `healthy`;
- `stale`;
- `unavailable`;
- `corrupt`;
- `blocked`;
- `unsupported`.

### How it connects

Status combines information from configuration, registry state, vault scanning,
Markdown lint, proposals, ownership, recovery transactions, graph
publications, and export publications.

Use it as the engine-room gauge. A stale optional view usually needs rebuilding.
A blocked recovery transaction or corrupt canonical state deserves attention
before consequential work continues.

## 3.6 Context search and context packs

### What it is

A context pack retrieves relevant canonical notes for a question and explains
why they matched. An explicit focus path can also force the current source or note
into the pack even when its words do not match the question strongly enough for
lexical retrieval.

```bash
lifeos context build \
  "Why do I avoid long study sessions?"

lifeos context build \
  "What matters while I study this for the driving-licence exam?" \
  --focus-path study/driving-licence/intersections.md \
  --limit 12 \
  --json
```

The result may contain applicable instructions, explicitly focused sources,
other matching canonical notes, score evidence, excerpts, parser diagnostics,
evidence gaps, and omissions. `vault_context` exposes the same bounded
pre-reasoning context to an MCP-connected agent; it does not ingest or mutate
anything by itself.

### How it connects

Context packs combine:

- Markdown metadata;
- note contents;
- typed instructions from `system/instructions.yml`;
- deterministic token-aware lexical scoring;
- source-level diagnostics.

They provide bounded evidence for an AI agent or human review without loading
the entire vault.

Example instruction file:

```yaml
schema_version: 1
instructions:
  - id: prefer-primary-study-sources
    authority: system
    scope: domain
    priority: 100
    text: Prefer textbook and primary-source evidence over unsourced summaries.
    domains:
      - study
      - wiki
    query_terms:
      - biology
      - physiology
      - evidence
```

Only the allowlisted `system/instructions.yml` file grants routed instruction
authority.

## 3.7 Study and flashcards

### What it is

The study module loads due flashcards and builds a time-bounded review workload.

Example flashcard:

```md
---
id: card-cell-membrane-001
type: flashcard
status: active
topic: Cell Biology
question: What is the main structural basis of the cell membrane?
answer: A phospholipid bilayer containing proteins, cholesterol, and carbohydrates.
due: 2026-07-16
estimated_seconds: 45
source_refs:
  - study/cell-biology/chapter-03.md
---
```

Build a review session:

```bash
uv run lifeos study review --minutes 20
```

### How it connects

Flashcards reference study and wiki notes through `source_refs`. The optimizer:

- includes cards whose due date has arrived;
- prioritizes overdue material;
- respects the available-time budget;
- groups cards into topic sessions;
- reports due cards that could not fit.

It creates a review workload rather than one task per card.

## 3.8 Goals, plans, and adaptive daily planning

### What it is

Plans hold outcomes, context, and embedded actions.

```md
---
id: plan-cell-biology-foundation
type: plan
title: Build a Cell Biology Foundation
description: Finish the introductory textbook and create durable notes.
status: active
goal: goal-understand-modern-biology
desired_outcome: Explain major cellular systems without relying on memorized phrases.
review_date: 2026-07-20
tasks:
  - task_id: cell-read-chapter-03
    title: Read chapter 3
    status: todo
    duration: 45
    energy: medium
    motivation: medium
    mode: reading
    due: 2026-07-18
    blocked_by: []
---
```

Generate today's proposed menu:

```bash
uv run lifeos plan today \
  --minutes 120 \
  --energy medium \
  --motivation low
```

### How it connects

The planner reads active plan notes and considers unresolved blockers, due-date
urgency, duration, available time, energy, motivation, work mode, and plan
diversity. The result is a **proposed menu**, not an order.

## 3.9 Journal, metrics, and personal observation

### What it is

Journal notes can contain prose, metrics, units, definitions, and activity tags.

```md
---
type: journal
date: 2026-07-16
status: active
metrics:
  sleep_hours: 7.5
  morning_energy: 7
  motivation: 6
metric_units:
  sleep_hours: hours
  morning_energy: score_0_to_10
activities:
  - sunlight
  - walking
---
```

Analyze two numeric metrics:

```bash
uv run lifeos observe patterns \
  --outcome morning_energy \
  --factor sleep_hours
```

Compare days with and without an activity:

```bash
uv run lifeos observe patterns \
  --outcome evening_energy \
  --activity weight-training \
  --min-samples 8
```

### How it connects

Observation reads journal records and produces tentative reports with sample
counts, raw and standardized effects, uncertainty intervals, evidence strength,
missing-data diagnostics, freshness, and explicit noncausal caveats.

A useful finding is not automatically promoted into canonical truth. Review it
before writing or proposing a durable pattern note.

## 3.10 MCP-only agent-assisted ingestion

### What it is

Ingestion lets an external agent connected to the local LifeOS MCP server turn
new evidence into **zero or more reviewable changes**. LifeOS does not run an
embedded model client and does not accept model names or provider API keys.

A source may come from any relevant registered canonical Markdown area, for
example `raw/`, `study/`, `journal/`, `experiments/`, or `goals/`. Its folder
provides semantic context; it is not a permission list for what may contribute to
knowledge.

For a context-sensitive source, the preferred agent flow is:

```text
registry_refresh
  → vault_read_markdown on the source
  → vault_context when goals, instructions, or nearby vault state may change
    how the source should be interpreted
  → wiki_search
  → vault_read_markdown on relevant wiki hits
  → agent decides whether durable knowledge should change
  → if no durable change is worthwhile: stop with no proposal
  → otherwise ingestion_evolve_wiki_proposal
      with 1..12 coordinated wiki creates and/or exact-section updates
  → stop at draft
```

`vault_context` is a read-only pre-reasoning tool, not an ingestion command. It
combines explicit focus paths with applicable `system/instructions.yml` rules and
relevant canonical context.

For a `study/` source, the agent may instead use
`study_evolve_learning_proposal`. The same atomic draft can contain wiki
mutations plus selective generated flashcards when retrieval practice materially
serves the inferred learning goal. The agent may infer, for example, exam-focused,
university-course, or self-study priorities from the source, goals, applicable
instructions, and surrounding vault context. LifeOS does not hard-code those
learning modes as a taxonomy. Automatic flashcard generation is not the default
for `raw/`, `journal/`, `experiments/`, or `goals/`; an explicit user request can
still ask for cards from any suitable material.

### How it connects

The MCP adapter reads canonical sources through the bounded facade. Registered
source identity and current hashes are verified before proposal generation. The
external agent interprets the evidence and chooses what would make the vault more
useful, while LifeOS validates paths, ownership, operation budgets, hashes, and
proposal state.

`ingestion_evolve_wiki_proposal` accepts 1..12 distinct generated-page creates
and/or ownership-aware exact-section updates in one atomic draft. Generated
creates may choose useful nested paths such as
`wiki/learning/retrieval-practice.md`; approved application can create missing
nested folders beneath the existing canonical `wiki/` root. The old
`page_kind + slug` route remains a compatibility API but is not the preferred
workflow. No parallel `wiki/sources/` mirror is required merely because evidence
exists elsewhere in the vault.

`study_evolve_learning_proposal` applies the same bounded proposal discipline to
a registered `study/` source and may additionally create generated cards beneath
the existing canonical `flashcards/` root. New nested folders can emerge on
approved application, but LifeOS does not silently invent missing canonical
roots. Generated cards keep source references to the study material and may also
reference the durable wiki knowledge they test.

Existing-note updates require one unique ATX heading (the heading text is
supplied without `#` markers). Human-owned targets produce a base-hash-bound
human-file patch. Generated-owned targets require matching generator ownership
and content hashes. Every mutation includes a concise rationale. Neither
ingestion tool directly overwrites canonical notes, and creating a draft never
implies permission to submit, approve, or apply it.

## 3.11 Proposal lifecycle, ownership, and recovery

### What it is

Consequential changes follow a durable lifecycle:

```text
draft → pending → approved → applied
                  ↘ rejected
                  ↘ stale
```

Each proposal lives under:

```text
proposals/<proposal-id>/
  proposal.md
  patches.json
  review.json
```

`patches.json` contains the operations LifeOS may apply. For new proposals,
`review.json` preserves the exact red/green diff that was shown for those
operations, so proposal history remains readable after later vault changes.
Older proposals without `review.json` remain visible with a **Legacy live
preview** warning; their historical diff may not be reconstructable.

Generated-file authorization is tracked in:

```text
system/generated-ownership.json
```

### How it connects

Before application, LifeOS verifies approval, review digest, target hashes,
generated-file ownership, managed-block validity, and recovery state.

Application writes targets, ownership, and proposal state through a
recovery-aware state machine. Interrupted work remains detectable and blocks new
application until recovery has completed.

Useful commands:

```bash
uv run lifeos proposals list
uv run lifeos proposals list --status pending
uv run lifeos proposals migrate-lifecycle --dry-run
uv run lifeos proposals migrate-lifecycle
```

Approval and application are exposed through the typed facade and MCP adapter,
not direct CLI subcommands.

## 3.12 Typed facade and MCP adapter

### What it is

The facade exposes bounded models for external agents. The local MCP server makes
those tools available over STDIO. Normally the MCP client launches the server
using the application executable and the vault-root configuration file; see the
[Setup & Installation Guide](04-setup-and-installation.md) for the concrete Codex
registration command.

### How it connects

The MCP adapter calls the same deterministic facade used by internal code.
Consequential actions invoke a trusted interactive authorizer. The agent supplies
only allowed fields and cannot claim the approving identity or bypass
confirmation.

Three instruction layers stay separate:

- the application repository's `AGENTS.md` guides development of LifeOS;
- MCP server instructions advertise client-independent LifeOS runtime rules;
- the vault's `system/instructions.yml` supplies vault-specific instructions that
  `vault_context` can route to the current question and focus paths.

The preferred runtime surfaces include `registry_refresh`,
`vault_read_markdown`, `vault_context`, `wiki_search`,
`ingestion_evolve_wiki_proposal`, `study_evolve_learning_proposal`, and the
explicit proposal lifecycle tools. `runtime_activity` is a read-only diagnostic
surface that reports recent MCP routing metadata such as tool names, paths,
instruction IDs, proposal IDs, and changed paths without copying canonical note
bodies or flashcard answers into the activity log. This makes “what did the MCP
server do?” inspectable without coupling a client to `.lifeos/`'s internal file
format.

All ingestion paths stop at the resulting draft unless the user separately asks
for submission, approval, or application. Orphaned ownership, generator mismatch,
hash mismatch, missing canonical roots, or stale source state fail closed.

## 3.13 Graph views

### What it is

LifeOS generates disposable graph views:

```text
knowledge
provenance
personal-patterns
system
```

```bash
uv run lifeos graph build knowledge
uv run lifeos graph status knowledge --json
```

### How it connects

Graph construction extracts stable nodes, wikilinks, explicit relations,
provenance relationships, and domain-specific layers. Outputs are published
under `.lifeos/graphify/` through generation-based publication and integrity
manifests.

Graph data is a view, not authority. A visually interesting connection is a
question to inspect, not a fact promoted by geometry.

## 3.14 Purpose-specific exports

### What it is

Exports create bounded products rather than cloning the whole vault.

| Export kind | Typical contents |
| --- | --- |
| `public-wiki` | Public, non-archived notes from `wiki/` |
| `study-bundle` | Study, wiki, and flashcard material |
| `trusted-agent` | System, goals, plans, wiki, study, and patterns |
| `personal-review` | Journal, metrics, patterns, goals, plans, and reviews |

```bash
uv run lifeos export build public-wiki
uv run lifeos export status public-wiki
```

### How it connects

Exports select notes according to product policy, preserve relative structure,
convert wikilinks into portable links, record source and rendered hashes, and
verify active-generation integrity.

Public exports fail closed: private, archived, malformed, ambiguous, or unsafe
material is not silently assumed publishable.

## 3.15 First-class review artifacts

### What it is

Daily and weekly reviews are durable Markdown notes rather than transient wizard
state. Daily notes combine morning and evening phases. Weekly notes use ISO-week
identity. Managed evidence is isolated from human reflection, and progress,
decisions, continuity, and lifecycle state remain inspectable in frontmatter.

### How it connects

The review workspace reads deterministic snapshots from the Python bridge, links
check-ins and task outcomes, carries exact evidence fingerprints forward, and
creates draft proposals for changes outside the artifact. Legacy review notes can
be previewed and migrated without deleting their sources. Disposable indexes can
be rebuilt from Markdown after `.lifeos/` is removed. See
[First-Class Daily and Weekly Reviews](10-first-class-reviews.md).


## 3.16 Semantic retrieval and knowledge conversations

### What it is

An evidence-first Obsidian workspace combines exact, lexical, semantic, metadata,
link, and optional graph retrieval. Saved conversations are canonical Markdown;
chunks, embeddings, and ranking state are disposable.

### How it connects

The Python bridge enforces scope and privacy policy, exposes ranking components,
validates citations, detects changed evidence, and creates proposal previews for
reviewed conversation outcomes. Missing providers degrade to local retrieval, and
removing `.lifeos/retrieval/` triggers a rebuild rather than knowledge loss. See
[Semantic Retrieval and Knowledge Conversations](11-semantic-retrieval-and-knowledge-conversations.md).


## 3.17 Personal experiments

### What it is

A canonical experiment artifact keeps a bounded question, protocol, baseline,
intervention phases, measures, observations, amendments, safety classification,
descriptive analysis, conclusion, and lineage together.

### How it connects

The Obsidian workspace guides design and tracking while Python validates lifecycle,
safety, schedules, missing-data semantics, analysis, history, migration, privacy,
and recovery. Review surfaces use evidence fingerprints, and every follow-up change
to another canonical artifact goes through proposals. See
[Personal Experiments](12-personal-experiments.md).


## 3.18 Rich capture for meals, exercise, and attachments

### What it is

Rich capture stores a real-world observation as canonical Markdown and preserves
original attachment bytes through content-addressed, vault-relative storage. It
keeps user statements, local extraction, provider suggestions, confirmations,
and disposable views in separate layers.

### How it connects

The Python bridge owns stable identities, lifecycle validation, attachment
hashing and deduplication, local extraction, inference decisions, links, merge
and split, privacy previews, proposal creation, migration, and recovery. Daily
and weekly reviews can surface capture evidence; semantic retrieval and
knowledge conversations can use approved text; experiments require explicit
mapping and confirmation before a capture value becomes a measurement.

The standard plugin currently registers ribbon and command-palette capture, meal
and exercise quick capture, selected-text capture, and active-capture loading.
Other controller origins, provider-backed OCR or transcription, exclusion
toggles, destructive deletion, and several bulk actions need additional UI or
host wiring. See [Rich Capture for Meals, Exercise, and Attachments](13-rich-capture.md).

---

[← Previous: Executive Summary & Philosophy](02-executive-summary-and-philosophy.md) · [Manual home](README.md) · [Next: Setup & Installation →](04-setup-and-installation.md)