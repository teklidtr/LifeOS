---
id: LIFEOS-1211
title: Validate and release the goal-to-plan copilot
status: backlog
phase: 12
depends_on:
  - LIFEOS-1201
  - LIFEOS-1202
  - LIFEOS-1203
  - LIFEOS-1204
  - LIFEOS-1205
  - LIFEOS-1206
  - LIFEOS-1207
  - LIFEOS-1208
  - LIFEOS-1209
  - LIFEOS-1210
risk: high
---

# Goal

Ship the goal-to-plan copilot as a safe, provider-neutral, reversible workflow
with complete end-to-end tests, migration coverage, and user documentation.

# Scope

- Add end-to-end fixtures covering vague goals, ready goals, exploratory goals,
  competing plan options, overload, existing-plan duplication, study plans,
  changed constraints, repeated avoidance, and goal review.
- Test deterministic-only operation and model-assisted operation through fixture
  adapters.
- Test context preview, clarification, option comparison, rolling-wave
  decomposition, capacity checking, explanation, editing, proposal creation,
  approval, application, recovery, and later replanning.
- Add compatibility checks across Python schemas, bridge protocol, plugin types,
  proposal schemas, and model-adapter contracts.
- Add performance budgets for large vault indexes and realistic planning context.
- Add migration and removal tests proving that canonical goals and plans remain
  readable without copilot state.
- Update `docs/architecture.md`, `docs/design-decisions.md`, and
  `docs/roadmap.md` to match shipped behavior.
- Add `docs/user-manual/09-goal-to-plan-copilot.md` covering:
  - when to create a goal, experiment, or plan
  - context preview and privacy controls
  - clarification sessions
  - comparing plan options
  - milestones and rolling-wave actions
  - capacity and conflict findings
  - explanations and assumptions
  - proposal review and stale edits
  - replanning, pausing, superseding, and closing
  - offline or no-model behavior
  - troubleshooting, recovery, and removal
- Update chapter navigation and validate all manual links.

# Out of scope

- Claims that the copilot improves productivity, health, or happiness in general.
- Cloud telemetry or cross-user evaluation.
- A general semantic knowledge conversation workspace.
- Autonomous goal selection, plan approval, or daily scheduling.
- Mobile parity.

# Required invariants

- The complete workflow remains optional and reversible.
- No model-specific repository files are required.
- Invalid or unavailable model output never blocks deterministic vault use.
- Evaluation does not create one hidden quality or productivity score.
- Documentation describes only shipped behavior and visible limitations.
- Removing disposable copilot state preserves canonical goals, plans, proposals,
  and decision lineage.

# Required tests

- Full new-goal to applied-plan flow.
- Experiment-first, park, abandon, and no-plan outcomes.
- Existing-plan linking and duplicate suppression.
- Baseline and adaptive capacity comparisons.
- Context denial, redaction, stale source, malformed output, and model timeout.
- Plugin and bridge restart during each major workflow stage.
- Proposal interruption and recovery.
- Goal review and rolling replanning after changed evidence.
- Schema migration, incompatible-version rejection, and derived-state rebuild.
- Keyboard-only critical paths and manual link validation.

# Acceptance criteria

- A new user can understand and operate the copilot entirely from Obsidian after
  installation.
- The release is provider-neutral, bounded, explainable, and proposal-gated.
- All Python and TypeScript tests, lint, type checks, builds, release checks, and
  Markdown validation pass.

# Validation commands

```bash
pytest -q
ruff check src tests
mypy src
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
./scripts/validate-release.sh
python scripts/validate_manual_links.py
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-007: Native Obsidian references first
- DD-014: Context packs use multiple retrieval modes
- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-023: Tasks stay with plans
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
