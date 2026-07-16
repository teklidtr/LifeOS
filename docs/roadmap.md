# LifeOS Roadmap

Implementation follows rolling-wave planning. Only the current phase should be decomposed in detail.

## Phase 0: Project skeleton

Preserve the architecture and establish a controlled implementation workflow.

## Phase 1: Deterministic foundation

LifeOS can inspect a vault and explain exactly what changed.

Capabilities:

- configuration loader
- vault scanner
- SQLite registry and migrations
- hashes and stable source IDs
- generated-file ownership
- structural lint
- CLI status

## Phase 2: Proposal engine

Agents can propose consequential changes without directly mutating important notes.

## Phase 3: First ingestion vertical slice

One Markdown study source can produce a traceable wiki proposal.

## Phase 4: Indexes, routing, and context packs

Agents can find relevant evidence without loading the full vault.

## Phase 5: Study and flashcards

Study work, durable knowledge, and review workloads form one traceable loop.

## Phase 6: Adaptive planning

LifeOS proposes a realistic daily menu from approved goals and plans.

## Phase 7: Personal observation

LifeOS surfaces tentative patterns without presenting them as truths.

## Phase 8: Graphify integration

Relationship analysis improves discovery without becoming authoritative.

## Phase 9: Optional exports

Generate purpose-specific knowledge products such as a public wiki, study bundle, trusted-agent bundle, or personal-review bundle.

## Phase 10: Obsidian-native daily interaction

Obsidian becomes the primary LifeOS cockpit. A thin desktop plugin uses the
existing typed Python core for all planning, study, status, proposal, recovery,
and canonical-write behavior.

Capabilities:

- local desktop bridge with versioned typed contracts
- Today dashboard
- quick capture and morning/evening check-ins
- task outcomes and execution history
- proactive attention queue for unaccounted outcomes
- study-session controls
- guided daily and weekly reviews
- proposal review and system-health UI
- optional background notifications while Obsidian is closed
- desktop end-to-end packaging and release

The accepted architecture is documented in `docs/obsidian-desktop-architecture.md`.
Implementation proceeds through `LIFEOS-1001` to `LIFEOS-1012`.

## Phase 11: Adaptive-planning feedback loop

LifeOS learns cautiously from explicit execution outcomes and reconciliation
history. It improves duration forecasts, task-capacity fit, and avoidance
questions while keeping the original planner available as a visible baseline.

Capabilities:

- deterministic, rebuildable execution-feedback evidence
- cautious duration calibration with hierarchical fallbacks
- separate energy and motivation fit signals
- repeated-avoidance and stalled-task diagnosis
- off, shadow, and active adaptive-planning modes
- baseline-versus-adaptive explanations and counterfactuals
- Obsidian-native correction, dismissal, disable, and reset controls
- feedback-driven plan-improvement proposals
- historical replay, migration, end-to-end validation, and user-manual updates

Phase 11 is shipped. The accepted architecture is documented in
`docs/adaptive-feedback-architecture.md`, and the user workflow is documented in
`docs/user-manual/08-adaptive-planning.md`.

Delivered release capabilities include canonical adaptive preferences,
historical replay without outcome leakage, conservative schema migration,
feedback-driven proposals, recovery testing, Obsidian keyboard paths, fixture
histories, and versioned Python/plugin release checks.

## Phase 12: Goal-to-plan copilot

LifeOS helps the user turn a broad goal or emerging intention into reviewable
medium-term plan options and a deliberately small set of near-term actions. The
workflow is conversational, but canonical changes remain proposal-gated and
rolling-wave planning prevents false precision.

Shipped capabilities:

- deterministic goal-readiness diagnostics
- bounded, previewable planning context packs
- guided clarification that may conclude with plan, experiment, park, or no action
- structured alternative plan options with visible assumptions and tradeoffs
- milestone planning with only the current wave decomposed into tasks
- portfolio capacity and conflict checks without a universal productivity score
- provenance, explanations, comparisons, and counterfactuals
- safe goal and plan proposals using existing validation and recovery
- an Obsidian-native copilot workspace
- goal review and rolling replanning linked to explicit execution evidence
- provider-neutral adapters, deterministic fallback, end-to-end tests, and user-manual coverage

Phase 12 is shipped. The accepted architecture is documented in
`docs/goal-to-plan-copilot-architecture.md`, and the complete user workflow is
in `docs/user-manual/09-goal-to-plan-copilot.md`.

Delivered release coverage includes deterministic-only and fixture-adapter
flows, context denial and redaction, duplicate-plan suppression, baseline and
adaptive capacity comparisons, proposal recovery, living replanning, large-vault
budgets, schema compatibility, derived-state rebuild, plugin keyboard paths, and
manual-link validation.

## Phase 13: First-class daily and weekly review artifacts

LifeOS promotes daily and weekly reviews from transient guided workflows into
durable, inspectable Markdown artifacts. A review can be opened, edited, resumed,
linked, completed, and revisited directly in Obsidian without depending on
disposable runtime state.

Shipped capabilities:

- versioned daily and weekly review artifact contracts
- one canonical daily artifact with morning and evening phases
- canonical weekly artifacts with ISO-week identity and explicit date ranges
- managed deterministic snapshots separated from human-owned reflection
- durable progress, answers, item decisions, and review lifecycle
- continuity links and carry-forward without silently duplicating obligations
- proposal-gated actions for changes outside the review artifact
- queryable review history, due-state, and completion summaries
- an Obsidian-native review workspace and history browser
- migration from legacy morning, evening, and weekly review notes
- rebuild, recovery, release validation, and user-manual coverage

Phase 13 shipped through `LIFEOS-1300` to `LIFEOS-1311`, including release fixtures, migration, rebuild, Obsidian workspace coverage, and user documentation.

