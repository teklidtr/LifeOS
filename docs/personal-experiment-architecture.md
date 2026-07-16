# Personal Experiment Architecture

## Status

Direction 6 introduces personal experiments as canonical Markdown and keeps all runtime indexes, analyses, schedules, and charts disposable.

## Product boundary

An experiment is a bounded attempt to learn from a deliberate change. A goal expresses a desired direction, a plan coordinates work, a task is an action, a habit is a repeated behavior, and a metric is an observation definition. An experiment connects those artifacts without replacing them.

The engine provides disciplined self-observation, not diagnosis or causal proof. Descriptive associations remain labelled as descriptive, missing values remain distinct from zero, and a valid outcome may be mixed, inconclusive, abandoned, or stopped for safety.

## Canonical layout

```text
experiments/
  YYYY/
    exp-<stable-id>.md
```

Each artifact contains versioned frontmatter plus managed Markdown views and human-owned sections. The protocol, lifecycle, measure definitions, observations, amendments, safety classification, analysis, conclusion, lineage, and timestamps are canonical. Runtime state under `.lifeos/experiments/` is rebuildable.

## Ownership

| Content | Authority |
|---|---|
| Protocol and amendments | Canonical experiment Markdown |
| User annotations and interpretation | Human-owned Markdown regions |
| Observations entered in the workspace | Canonical experiment Markdown |
| Derived summaries, indexes, calendars, and charts | Disposable runtime state |
| Changes to goals, plans, habits, tasks, notes, or reminders | Existing proposal lifecycle |
| AI suggestions | Optional drafts, never authority |

Managed refreshes may replace only named managed blocks. They must preserve human-owned text and use expected content hashes and idempotency keys.

## Lifecycle

`idea -> drafting -> baseline -> scheduled -> active -> paused -> completed -> analyzed -> archived`

Additional terminal or alternate paths include `abandoned` and early completion. Invalid transitions fail closed. Once baseline begins, material protocol edits become dated amendments rather than silent rewrites.

## Design warnings

Warnings are separate, inspectable findings with codes, severity, evidence, explanation, and recommended action. Non-safety warnings may be acknowledged. Blocking safety findings cannot be overridden by the experiment workflow.

Checks include multiple simultaneous interventions, vague outcomes, missing comparison or baseline, sparse cadence, inadequate duration, retrospective-only collection, indistinguishable adherence, duplicate or overlapping experiments, confounders, and unsafe content.

## Safety

Deterministic policy blocks medication changes, severe symptoms, dangerous physiological targets, pregnancy-related intervention planning, eating-disorder or self-harm contexts, dangerous restriction, overtraining, sleep deprivation, substance misuse, and illegal activity. Blocked artifacts may remain informational drafts with a user-visible classification and explanation, but cannot be scheduled or activated.

Emergency or severe-symptom text returns immediate-safety guidance and stops the workflow. No hidden reasoning is stored.

## Measures and missing data

Measures have stable IDs, kinds, units, cadence, source, direction, valid range, missing-data behavior, aggregation, and role. Observation states are explicit: `measured`, `not-measured`, `not-applicable`, `skipped`, and `unavailable`. Only `measured` observations may carry a value.

Links to diary entries, reviews, check-ins, habits, tasks, metrics, photos, and source notes preserve provenance instead of copying unrelated canonical data.

## Scheduling

Schedules are timezone-aware and pause-aware. They may use daily, weekly, selected-day, or phase-relative cadence, flexible windows, grace periods, and before/after anchors. Experiment schedules describe intended collection. Mutations to external tasks, reminders, or calendar-like structures remain proposal-gated.

## Deterministic analysis

The local analysis engine calculates observation counts, adherence and missing-data rates, phase averages, medians, ranges, changes from baseline, simple trends, and day-of-week summaries when data shape permits. Every result records the actual observation IDs, missing-data treatment, assumptions, limitations, and whether it is descriptive or inferential. Direction 6 ships descriptive methods only.

Conclusions use an explicit vocabulary and never claim causation. Raw observations remain inspectable behind every result.

## Reviews

Daily reviews surface only experiments relevant that day, due or missed observations, stop-rule warnings, and unacknowledged amendments. Weekly reviews surface active and recent experiments, adherence, missingness, amendments, confounders, descriptive trends, and readiness for analysis. Evidence fingerprints reuse existing dismissal and carry-forward behavior.

## Provider neutrality and privacy

Creation, tracking, analysis, review integration, proposals, migration, and rebuild work without a model. Optional assistance uses provider-neutral capability metadata, bounded selected sources, disclosure, cancellation, timeout, malformed-output handling, redaction, and deterministic adapters.

Protected and sensitive scopes default to local-only. Linked content is never automatically transmitted. Logs exclude full observation text and values by default.

## Recovery and migration

Indexes and analyses rebuild from canonical Markdown with checkpoints. Rebuild detects malformed artifacts, unsupported schemas, duplicate IDs, renamed files, missing links, and orphaned observations. Legacy migration is previewed, source-hash guarded, resumable, audited, and preserves originals.

## Obsidian workspace

The plugin is a thin typed client. Ribbon and contextual commands open graphical design, tracking, analysis, evidence, proposal, and history surfaces. Explicit states cover loading, empty, malformed, stale, unsupported schema, missing index, rebuild, provider failure, blocked safety, insufficient evidence, conflicts, proposal states, and migration. Controls expose labels, predictable focus, keyboard navigation, and screen-reader status text.

## Sequenced implementation

| Task | Capability |
|---|---|
| LIFEOS-1500 | Architecture, dependency audit, and task design |
| LIFEOS-1501 | Canonical contracts, lifecycle, amendments, and persistence |
| LIFEOS-1502 | Design guidance, safety policy, scheduling, and provider-neutral assistance |
| LIFEOS-1503 | Observations, deterministic analysis, visual models, and history/index rebuild |
| LIFEOS-1504 | Review integration and proposal-based follow-up actions |
| LIFEOS-1505 | Bridge protocol and experiment application service |
| LIFEOS-1506 | Obsidian experiment workspace and accessible entry points |
| LIFEOS-1507 | Migration, privacy, recovery, performance, and deterministic fixtures |
| LIFEOS-1508 | Documentation, end-to-end validation, reports, and release packaging |
