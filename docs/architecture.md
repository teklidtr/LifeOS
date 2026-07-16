# LifeOS Architecture

## System layers

### Markdown vault

The vault is canonical human-readable state.

Typical domains:

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
system/
```

### Deterministic layer

Scripts establish facts:

- file discovery and hashes
- stable IDs and provenance
- generated-file ownership
- proposal application
- task extraction
- index generation
- link and citation validation
- graph dirty-state tracking
- structural lint

### Agent layer

Agents interpret meaning:

- classify and synthesize sources
- decompose goals
- propose wiki edits
- create flashcards
- interpret repeated avoidance
- identify candidate patterns and contradictions
- explain evidence coverage

Agents do not silently promote interpretations into truth.

### Human layer

The user controls goals, proposal approval, personal interpretations, policy changes, pattern promotion, and archival decisions.

## Proposal engine

Consequential changes are stored under:

```text
.lifeos/proposals/<proposal-id>/
  proposal.md
  patches/
```

A deterministic tool applies only explicitly approved items whose target hashes still match.

## Registry

The registry stores file hashes, source versions, derived outputs, proposal state, generated ownership, task records, graph state, and migrations.

It does not replace Markdown content.

## Managed content

```md
<!-- lifeos:managed:start block-name -->
Generated content
<!-- lifeos:managed:end block-name -->
```

Markers must be unique, non-nested, and paired. Creation or deletion requires proposal approval.

## Adaptive planning

Tasks stay close to plans and are globally indexed by scripts.

```text
long-term goal    broad direction
medium-term plan  clear outcome and milestones
near-term actions detailed one or two weeks ahead
today menu        selected from eligible actions
```

The planner proposes a menu rather than issuing commands.

## Adaptive feedback layer

Explicit execution outcomes are normalized into a deterministic, rebuildable
evidence dataset. Cautious duration calibration, separate energy and motivation
fit, and repeated-avoidance hypotheses may adjust the daily recommendation only
through an optional bounded policy. The original planner remains visible as the
baseline, and plan changes require proposals. See
[Adaptive-Planning Feedback Architecture](adaptive-feedback-architecture.md).

## Graph layer

Graphify is an optional helper behind a LifeOS skill.

```text
.lifeos/graphify/
  knowledge/
  provenance/
  personal-patterns/
  system/
```

Graphify supplies paths, communities, bridge nodes, and visualization. LifeOS controls inputs, stable IDs, evidence classes, validation, and proposal generation.

## Context packs

A context pack assembles applicable policies, the question, source excerpts, graph-discovered candidate paths, recent context, evidence gaps, and omissions.

## Optional exports

Purpose-specific bundles may be generated under `.lifeos/exports/`, such as a public wiki, biology study bundle, trusted-agent bundle, or personal-review bundle. They are optional products, not mirrors of the vault.

## Obsidian desktop interaction

Obsidian is the primary human interface. A thin TypeScript plugin launches a vault-scoped
Python bridge over versioned JSON-RPC/STDIO. Python remains the sole implementation of
business rules and canonical writes. Direct UI writes use expected content hashes and
idempotency keys. Consequential agent-generated changes remain proposals with trusted
interactive authorization. See [Obsidian Desktop Architecture](obsidian-desktop-architecture.md).

## Adaptive feedback release architecture

Adaptive planning is shipped as a bounded layer above the baseline planner.
Canonical execution events, corrections, exclusions, mode preferences, diagnosis
dismissals, and reset boundaries remain in the Markdown vault. The normalized
evidence dataset and historical replay results are disposable.

The Obsidian Today view reads `system/adaptive-planning.yml` by default. An
explicit request may temporarily override the mode, but it does not rewrite the
canonical preference. Off returns the baseline menu, Shadow computes the
adaptive candidate while returning baseline, and Active may return the adaptive
candidate. All modes preserve baseline output for comparison.

Historical replay is read-only and prevents outcome leakage by using only events
strictly earlier than each replayed planning day. Evaluation reports separate
measures such as unused time, overflow, missing outcomes, completion fraction,
estimate error, and explanation coverage. It never combines them into a hidden
user score.

Legacy adaptive preferences require an explicit migration. Legacy enabled state
migrates to Shadow rather than Active. Unsupported future schemas fail closed.
Plan-improvement findings become ordinary Git-tracked proposals and reuse the
same validation, stale-write, authorization, application, and recovery state
machine as every other consequential change.

## Goal-to-plan copilot

The optional goal-to-plan copilot turns an explicitly selected direction into
clarification, experiment, link, park, or reviewable plan options. Readiness,
context inclusion, rolling-wave depth, portfolio fit, and proposal application
are deterministic boundaries. Model adapters only create validated suggestions.
The user previews context and edits drafts in Obsidian; canonical changes still
use the existing proposal lifecycle. See
[Goal-to-Plan Copilot Architecture](goal-to-plan-copilot-architecture.md).

Planning sessions and replanning reviews live under disposable `.lifeos/`
runtime state. Goals, plans, proposals, execution evidence, review notes, and
applied decision lineage remain canonical Markdown. Removing the runtime state
cannot remove or rewrite those canonical files, and rebuilding the index
rediscovers them.

Daily attention and weekly review may surface a planning or replanning prompt
from explicit evidence. The review is recalculated from current canonical state,
keeps the original decision lineage inspectable, suppresses only an unchanged
rejected evidence fingerprint, and creates a proposal for every consequential
change. Continue unchanged creates no proposal.

The shipped bridge exposes versioned readiness, context, session, option,
decomposition, capacity, explanation, proposal, and replanning capabilities.
The Obsidian workspace is the primary interaction surface. Provider adapters are
optional, provider-neutral, schema-bounded, and fail back to deterministic
operation when missing, invalid, or timed out.


## First-class review artifacts

Daily and weekly reviews are canonical Markdown under `reviews/daily/` and
`reviews/weekly/`. One daily artifact contains morning and evening phases; weekly
artifacts use ISO-week identity and explicit period boundaries. Managed facts,
items, continuity, and completion summaries are separated from human-owned
reflection by validated managed blocks.

Progress, prompt answers, item decisions, lifecycle events, proposal references,
snapshot lineage, and migration lineage live in frontmatter. Runtime indexes under
`.lifeos/reviews/` are disposable and rebuild from the artifacts. Review refreshes
require optimistic concurrency and preserve human Markdown byte-for-byte outside
managed blocks. External canonical changes remain draft proposals until the shared
submit, approve, and apply lifecycle completes.

The Obsidian review workspace is a thin typed client for Python bridge methods. It
opens today, the current ISO week, active artifacts, and history; handles stale and
blocked states; and exposes explicit migration preview and index rebuild actions.
Legacy source files remain untouched after migration. See
[Review Artifact Architecture](review-artifact-architecture.md) and
[First-Class Daily and Weekly Reviews](user-manual/10-first-class-reviews.md).

## Semantic retrieval and knowledge conversations

Semantic retrieval is an additional, derived discovery layer over canonical
Markdown. Structural chunks, embeddings, link tables, ranking state, and rebuild
journals live under `.lifeos/retrieval/` and use index schema version 1. A complete
rebuild writes to staging and publishes atomically; incremental synchronization
handles creates, edits, stable-ID moves, content-preserving renames, and deletes.
Missing, stale, interrupted, corrupt, and incompatible states expose explicit
recovery plans.

Hybrid ranking keeps exact, lexical, semantic, metadata, link, optional graph,
pin, and optional reranking signals separate and inspectable. Filters and
protected-scope policy run before ranking. Results preserve note path, heading,
line range, hashes, source metadata, duplicate provenance, and deterministic tie
ordering. No-provider mode retains all local non-vector signals.

Knowledge conversations are canonical Markdown under `conversations/YYYY/`.
Their managed block stores scope, turns, evidence fingerprints, validated
citations, branch lineage, provider disclosure, and lifecycle state. Human-owned
annotations remain outside the managed block. Deterministic citation validation
rejects nonexistent evidence and marks changed or deleted sources stale.
Conversation outcomes create ordinary proposals with exact targets, patches,
evidence, and stale-target hashes. They never mutate another note directly. See
[Semantic Retrieval and Knowledge Conversation Architecture](semantic-retrieval-conversation-architecture.md)
and [Semantic Retrieval and Knowledge Conversations](user-manual/11-semantic-retrieval-and-knowledge-conversations.md).

## Personal experiments

Personal experiments are canonical Markdown artifacts under `experiments/YYYY/`.
The experiment application service owns schema validation, lifecycle transitions,
protocol amendments, explicit missing-data states, deterministic safety policy,
timezone-aware schedules, observations, descriptive analysis, lineage, migration,
privacy previews, and recovery audits. Human annotations remain outside managed
blocks and expected content hashes protect every write after a workspace load.

The derived experiment index and rebuild journal live under
`.lifeos/experiments/`. They can be deleted and rebuilt from Markdown. Daily and
weekly review adapters produce evidence-fingerprinted contextual items. Analysis
and history views are derived. Changes to goals, plans, tasks, habits, metrics,
notes, reminders, or calendar-like structures use the shared proposal engine.

The bridge exposes typed `experiment.*` capabilities, while the Obsidian plugin
remains a thin graphical client for design, tracking, analysis, evidence, history,
proposals, migration, and recovery. Local creation, tracking, analysis, and review
integration require no model. Optional assistance uses provider-neutral contracts
and bounded, inspectable source selection. See
[Personal Experiment Architecture](personal-experiment-architecture.md) and
[Personal Experiments](user-manual/12-personal-experiments.md).
