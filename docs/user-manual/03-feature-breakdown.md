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

Use either supported explicit file/proposal refresh adapter:

```bash
uv run lifeos scan
uv run lifeos scan --json
```

An MCP-connected agent can use `registry_refresh` for the same explicit
maintenance operation. Proposal-building ingestion tools also call the
authoritative full refresh automatically immediately before source verification,
so a separate refresh call is not required merely because an ingestion source is
new or edited. Neither surface rebuilds the separate provenance, semantic
retrieval, graph, or export indexes. See [Registry](../registry.md) for the exact
SQLite and refresh contracts.

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

A Context Pack is a bounded starting map for a question. Explicit focus paths are
validated and placed first, so the source you are actively working with does not
disappear merely because another note ranks more highly. The remaining slots use
the existing hybrid retrieval subsystem when its disposable index is healthy.
That ranking may combine exact/lexical matches, semantic similarity when a query
provider is configured, metadata, links, optional graph hints, pins, reranking,
and duplicate suppression.

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
other relevant canonical notes, excerpts, parser diagnostics, evidence gaps, and
omissions. Sources also carry bounded retrieval provenance such as
`retrieval_mode`, contributing retrieval-signal names, numeric ranking
components, and duplicate paths when those values are available. This explains
why deterministic retrieval selected evidence; it is not hidden model reasoning.

A missing, stale, corrupt, incompatible, or otherwise unavailable retrieval index
does not make `vault_context` unusable. LifeOS falls back to canonical
deterministic lexical retrieval and records the degraded capability in
`omissions`. A healthy index can still use its local non-vector signals when no
semantic query provider is configured. Protected scopes remain subject to the
same retrieval policy and default-deny behavior.

`vault_context` exposes this behavior to an MCP-connected agent without adding a
provider name, model name, or vector configuration to the tool request. It is
read-only and does not ingest or mutate anything by itself.

### How it connects

Context Packs combine:

- explicit focus-path precedence;
- the authoritative hybrid retrieval/index subsystem when healthy;
- deterministic lexical fallback over canonical Markdown;
- Markdown metadata and note contents;
- typed instructions from `system/instructions.yml`, evaluated against the final
  selected source set;
- source-level diagnostics, evidence gaps, omissions, and bounded retrieval
  explanation metadata.

They provide bounded evidence for an AI agent or human review without loading
the entire vault. They are deliberately not a one-shot crawl or answer engine.
After receiving the initial map, an agent can continue with `vault_list`,
`vault_search`, `vault_read_markdown`, `vault_read_many`, `vault_links`, or the
separate `wiki_search` operation. `wiki_search` intentionally remains a lexical
primitive so exact durable-wiki discovery stays composable with hybrid context
selection.

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
authority. Retrieval ranking does not turn an instruction into mutation
permission.

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

A source may come from any relevant canonical Markdown area, for example
`raw/`, `study/`, `journal/`, `experiments/`, or `goals/`. Its folder provides
semantic context; it is not a permission list for what may contribute to
knowledge. Proposal-building ingestion automatically refreshes the disposable
registry before verifying that source.

For a context-sensitive source, the preferred agent flow is:

```text
vault_read_markdown on the source
  → vault_context for an initial bounded context map when goals, instructions,
    or nearby vault state may change how the source should be interpreted
  → optionally continue agent-led exploration with vault_list, vault_search,
    vault_read_many, vault_links, or additional vault_read_markdown calls
  → wiki_search for exact/lexical durable-wiki discovery
  → vault_read_markdown on relevant wiki hits
  → agent decides whether durable knowledge should change
  → if no durable change is worthwhile: stop with no proposal
  → otherwise ingestion_evolve_wiki_proposal
      → automatic full registry refresh
      → registered-source/hash/target verification
      → 1..12 coordinated wiki creates and/or exact-section updates in a draft
  → stop at draft
```

`vault_context` is a read-only pre-reasoning tool, not an ingestion command. It
keeps explicit focus paths first, may use the shared hybrid retrieval subsystem,
falls back safely to deterministic lexical retrieval when derived state is not
healthy, and applies `system/instructions.yml` rules to the final selected source
set. The returned map does not decide what matters next. The external agent owns
that iterative choice. `registry_refresh` remains available as an explicit
maintenance operation outside this normal ingestion loop.

### External research-source capture

When the relevant source is not yet in the vault, the agent can start with
`research_query_context`. This composes the existing `vault_context` and
`wiki_search` surfaces and explicitly persists nothing. If existing LifeOS
knowledge is sufficient, the workflow ends with an answer and zero canonical
writes.

If the external agent identifies a material evidence gap, the agent performs the
research using its own provider/environment and submits only selected evidence
through `research_capture_evidence`. LifeOS does not browse the public web or run
a crawler itself. The capture tool creates or reuses a deterministic,
hash-bound `raw/research/` artifact containing source identity, snapshot hash,
external authorship metadata, and acquisition lineage explaining why the source
was collected. `captured_by` is not a caller-controlled MCP field; it comes from
the trusted local or authenticated runtime actor.

The returned `raw/research/...` path then enters the same ingestion flow shown
above. Proposal-building ingestion performs its normal registry preflight and
registered-source hash verification. If the captured evidence merely confirms
knowledge already represented in the wiki, the agent may stop with zero
proposals. Only a genuinely reusable durable delta should become an ordinary
reviewed proposal. See [Evidence-Grounded Research](18-evidence-grounded-research.md).

For a `study/` source, the agent may instead use
`study_evolve_learning_proposal`. The same automatic registry preflight runs
before source verification, and the atomic draft can contain wiki mutations plus
selective generated flashcards when retrieval practice materially serves the
inferred learning goal. The agent may infer, for example, exam-focused,
university-course, or self-study priorities from the source, goals, applicable
instructions, and surrounding vault context. LifeOS does not hard-code those
learning modes as a taxonomy. Automatic flashcard generation is not the default
for `raw/`, `journal/`, `experiments/`, or `goals/`; an explicit user request can
still ask for cards from any suitable material.

### How it connects

The MCP adapter reads canonical sources through the bounded facade. Immediately
before a proposal-building ingestion facade is invoked, it runs the existing
authoritative full registry refresh. Registered source identity and current hashes
are then verified against that fresh derived state. Refresh failures stop before a
draft is created. The external agent interprets the evidence and chooses what
would make the vault more useful, while LifeOS validates paths, ownership,
operation budgets, hashes, and proposal state.

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
`vault_read_markdown`, `vault_context`, `wiki_search`, `research_query_context`,
`research_capture_evidence`, `ingestion_evolve_wiki_proposal`,
`study_evolve_learning_proposal`, and the explicit proposal lifecycle tools.
`research_query_context` is a zero-write composition of existing context and wiki
search; `research_capture_evidence` is the narrow canonical exception that may
create/reuse a hash-bound external-evidence source in `raw/`. It does not expose
generic vault mutation or accept a spoofable capture actor.

`vault_context(question, focus_paths, limit)` remains provider-neutral: the caller
does not supply an embedding provider or vector-store setting. Its source payload
may add retrieval-mode/reason/ranking metadata while preserving the same tool name
and bounded request shape. `registry_refresh` is available for explicit
maintenance, while proposal-building ingestion performs its own automatic
preflight refresh. `runtime_activity` is a read-only diagnostic surface that
reports recent MCP routing metadata such as tool names, paths, instruction IDs,
proposal IDs, and changed paths without copying canonical note bodies or
flashcard answers into the activity log. This makes “what did the MCP server do?”
inspectable without coupling a client to `.lifeos/`'s internal file format.

All ingestion paths stop at the resulting draft unless the user separately asks
for submission, approval, or application. Orphaned ownership, generator mismatch,
hash mismatch, missing canonical roots, refresh failure, or source verification
failure after refresh fail closed.

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
chunks, embeddings, and ranking state are disposable. The same retrieval/index
subsystem now supplies Context Pack candidate selection rather than a separate
Context Pack vector or RAG implementation.

### How it connects

The Python bridge enforces scope and privacy policy, exposes ranking components,
validates citations, detects changed evidence, and creates proposal previews for
reviewed conversation outcomes. Missing providers degrade to local retrieval, and
removing `.lifeos/retrieval/` triggers a rebuild rather than knowledge loss.
Context Packs add focus-path precedence and instruction routing on top of these
retrieval contracts, while `wiki_search` remains an explicit lexical exploration
primitive. Research queries reuse these same retrieval surfaces rather than
creating another RAG engine; external evidence enters through the separate
hash-bound `raw/research/` capture boundary before it can ground a durable
proposal. See [Semantic Retrieval and Knowledge Conversations](11-semantic-retrieval-and-knowledge-conversations.md)
and [Evidence-Grounded Research](18-evidence-grounded-research.md).


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

## 3.19 Canonical personal working hypotheses

### What it is

LifeOS can recognize individual canonical working hypotheses as human-owned
Markdown under `patterns/`. A recognized artifact declares `pattern_schema: 1`
and `type: pattern`, then records a stable ID, the concise hypothesis statement,
lifecycle state, qualitative confidence, review reasons, origin, evidence
references, reviewed SHA-256 versions, and an evidence fingerprint.

These notes are hypotheses, not user truths, diagnoses, personality labels, or
instructions. `seed` means **track this hypothesis** while it remains exploratory.
`active` means **adopt this as useful working context for now** after explicit
review. `needs-review` means the evidence or timing deserves another look.
`confidence` remains separate from lifecycle and is never a numeric model
probability.

LifeOS uses the `personal-pattern-evidence` managed block for the refreshable
evidence summary. Reflection and other user prose before or after that block stay
human-owned. Markdown in `patterns/` without a recognized pattern schema remains
ordinary content.

### How it connects

The schema parser validates stable IDs, lifecycle values, evidence roles, safe
vault-relative evidence paths, exact lowercase SHA-256 digests, timestamps, and
portable optional evaluation parameters. Evidence references can be normalized
and fingerprinted deterministically while retaining supporting, contesting, and
contextual roles and the exact reviewed source versions. Parsing reads directly
from Markdown and does not require `.lifeos/` or another disposable runtime
database.

Pattern lifecycle changes use typed proposal builders rather than direct
canonical writes. **Track** creates a draft `create_file` proposal for an absent
human-owned `seed`; it does not create the pattern merely because a candidate was
detected. **Adopt** proposes `seed → active`. Revise, mark needs-review, resolve
review, change confidence, and archive operations produce base-hash-bound
`patch_human_file` proposals against the current pattern snapshot. Resolving a
review requires an explicit choice to return to `seed` or `active`, so finishing
a review does not silently mean adopting the hypothesis.

The draft records the transition reason and reviewed evidence fingerprint and
uses the ordinary proposal review snapshot. Rejection leaves canonical Markdown
unchanged, a stale target blocks application, and interrupted application uses
the shared proposal recovery machinery. The proposal builder does not choose an
approver and cannot approve or apply its own interpretation.

The aggregate Personal Model, automatic re-evaluation/review triggers, bounded
review/context integration, Obsidian workspace, and any planner influence remain
separate Phase 17 steps. In particular, a tracked or active pattern does not
silently become planner policy. See [Evidence-Backed Personal Model
Architecture](../personal-model-architecture.md).

---

[← Previous: Executive Summary & Philosophy](02-executive-summary-and-philosophy.md) · [Manual home](README.md) · [Next: Setup & Installation →](04-setup-and-installation.md)