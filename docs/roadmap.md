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
