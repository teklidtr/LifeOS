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

Typical top-level areas are:

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
proposals/
system/
```

You do not need every directory on day one. Add domains as they become useful.

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
- stable IDs;
- proposal index entries;
- source and provenance records.

These facts are stored in a disposable SQLite registry.

### How it connects

The registry supports:

- proposal listings and counts;
- file-change comparison;
- provenance lookup;
- status reporting;
- ingestion source validation.

It does **not** replace Markdown and should not contain the only copy of
canonical knowledge. The registry may be deleted and rebuilt.

Use either supported adapter; both call the same deterministic Python facade:

```bash
uv run lifeos scan
uv run lifeos scan --json
```

An MCP-connected agent uses `registry_refresh`. Refreshing the registry does not
rebuild the separate semantic retrieval, graph, or export indexes.

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
why they matched.

```bash
uv run lifeos context build \
  "Why do I avoid long study sessions?"

uv run lifeos context build \
  "What have I learned about thyroid physiology?" \
  --limit 12 \
  --json
```

The result may contain applicable instructions, matching notes, score evidence,
excerpts, parser diagnostics, evidence gaps, and omissions.

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

Ingestion turns a registered source note into a draft wiki proposal through an
external agent connected to the local LifeOS MCP server. LifeOS does not run an
embedded model client and does not accept model names or provider API keys.

```text
Ingest study/cell-biology/chapter-03.md into
wiki/cell-membrane.md using LifeOS.
```

The connected agent must use the advertised tools in this order:

```text
registry_refresh
  → vault_read_markdown
  → if the wiki target is absent:
      agent synthesizes a source-grounded title and body
      → ingestion_create_wiki_proposal
  → if one section of an existing wiki target must change:
      vault_read_markdown on the target
      → agent synthesizes that exact section's replacement body
      → ingestion_update_wiki_section_proposal
  → if a detailed page must be created and an existing section must point to it:
      vault_read_markdown on the existing target
      → agent synthesizes both bounded bodies
      → ingestion_create_wiki_and_update_section_proposal
  → stop at draft
```

### How it connects

The MCP adapter reads the canonical source through the bounded facade. The
external agent interprets the source, while LifeOS verifies its registered
identity and current hash, validates the supplied fields, creates a draft
proposal, and records provenance. Existing-note updates require one unique ATX
heading (the heading text is supplied without `#` markers). LifeOS checks the
canonical ownership manifest before publishing the draft. Human-owned targets
produce a base-hash-bound human-file patch; unchanged targets owned by the same
ingestion generator produce a generated-file replacement derived from the same
exact-section edit. Both preserve every surrounding section. It does not directly
overwrite the target wiki page, and ingestion alone never implies permission to
submit, approve, or apply the proposal.

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

The facade exposes bounded models for external agents. The local MCP server
makes those tools available over STDIO.

Start the server:

```bash
uv run lifeos-mcp \
  --config lifeos.yml \
  --actor-id "your-trusted-identity"
```

### How it connects

The MCP adapter calls the same deterministic facade used by internal code.
Consequential actions invoke a trusted interactive authorizer. The agent
supplies only allowed fields and cannot claim the approving identity or bypass
confirmation.

The server uses STDIO protocol output and should normally be launched by an
MCP-compatible client rather than used as an interactive shell command.

When an MCP client receives an ingestion request, the LifeOS server advertises
the bounded workflow explicitly: refresh the disposable registry with
`registry_refresh`, read the registered source with `vault_read_markdown`,
synthesize a source-grounded title and body, call
`ingestion_create_wiki_proposal` for an absent target, or read the existing
target and call `ingestion_update_wiki_section_proposal` for one exact section.
When one ingestion should do both, call
`ingestion_create_wiki_and_update_section_proposal`; its single draft contains
one generated-page creation followed by the ownership-appropriate hash-bound
update. An orphaned ownership entry, a generator mismatch, an ownership hash
mismatch, or a missing ownership manifest prevents draft publication and returns
bounded remediation. All paths stop at the resulting draft. Submission,
approval, and application each require a separate explicit user request and
retain trusted interactive authorization.

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
