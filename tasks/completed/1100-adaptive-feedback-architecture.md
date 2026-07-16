---
id: LIFEOS-1100
title: Define the adaptive-planning feedback architecture
status: completed
phase: 11
depends_on:
  - LIFEOS-1006
  - LIFEOS-1007
  - LIFEOS-1009
risk: high
---

# Goal

Define how LifeOS learns from task execution, omissions, estimates, energy,
motivation, and review outcomes without turning personal history into an opaque
score or a second source of truth.

# User outcome

The user can understand exactly which past observations influence today's menu,
correct wrong assumptions, disable unwanted learning, and return to the original
planner at any time.

# Scope

- Define the complete feedback loop from planned action to execution evidence,
  reconciliation, derived learning, planner adjustment, explanation, and review.
- Define the canonical execution evidence expected from LIFEOS-1006 and the
  computed attention evidence expected from LIFEOS-1007.
- Separate:
  - canonical user-recorded facts
  - deterministic derived statistics
  - tentative diagnoses
  - agent-generated proposals
  - ephemeral UI state
- Define a versioned feature vocabulary for task shape, plan, goal, mode,
  duration, time window, energy, motivation, blockers, outcome, and skip reason.
- Define minimum-evidence thresholds, hierarchical fallback rules, confidence
  labels, time decay, outlier handling, missingness, and contradiction handling.
- Define how user corrections, dismissals, disabled signals, and complete resets
  affect derived feedback.
- Define the planner integration boundary so adaptive evidence may adjust a
  recommendation but never silently rewrite canonical plans or task estimates.
- Define privacy boundaries and retention behavior for personal execution data.
- Define protocol contracts needed by the Obsidian plugin and local bridge.
- Add accepted design decisions and update architecture and roadmap documents.

# Required design questions

- Which execution fields are canonical and which are computed?
- Is feedback state rebuilt from canonical events, or does any durable derived
  state require explicit migration and backup?
- How are duplicate, corrected, or retracted execution records represented?
- How does LifeOS distinguish insufficient evidence from evidence of no effect?
- How are exact-task, plan-level, mode-level, and global fallbacks ordered?
- How strongly may learned evidence alter duration or ranking?
- How does the user inspect the original baseline recommendation?
- How are stale habits prevented from dominating current behavior?
- Which diagnoses are deterministic and which require a proposal-producing
  agent?
- What does a full reset remove, and what remains canonical history?

# Out of scope

- Implementing the execution-history capture UI.
- Black-box machine-learning models.
- Automatic modification of goals, plans, task estimates, or personal patterns.
- Health or psychological diagnosis.
- Cloud analytics, telemetry, or cross-user learning.
- Semantic knowledge retrieval.

# Required invariants

- Markdown remains canonical human-readable state.
- Silence is never interpreted as skipped or failed.
- Energy and motivation remain separate signals.
- Derived feedback is inspectable, disposable, and rebuildable.
- Every adaptive adjustment has evidence, confidence, and a baseline comparison.
- Sparse or contradictory evidence falls back safely to the nonadaptive planner.
- The user can disable, correct, or reset learning without deleting journal or
  execution history.
- No feedback result silently mutates a plan.

# Required deliverables

- Accepted design decisions for the feedback model and user-control boundary.
- A component and data-flow diagram.
- Versioned schemas for execution observations, derived feedback, explanation
  evidence, corrections, and reset markers.
- A fallback and confidence table.
- A threat and privacy model for personal execution history.
- A migration and compatibility strategy.
- A sequenced implementation plan aligned with LIFEOS-1101 through LIFEOS-1109.

# Acceptance criteria

- Every downstream Phase 11 task can rely on stable data and trust boundaries.
- The design explains behavior with and without sufficient evidence.
- Adaptive planning remains optional and reversible.
- No canonical write can occur merely because a statistical association exists.
- The Obsidian UI can expose all required controls without reimplementing Python
  business logic.
- Internal links and diagrams validate.

# Validation commands

```bash
git diff --check
python -m pytest tests/project -q
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-021: Adaptive planning, not conventional task management
- DD-025: Energy and motivation are distinct
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
- DD-033: SQLite disposability and rebuilding
