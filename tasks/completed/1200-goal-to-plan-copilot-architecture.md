---
id: LIFEOS-1200
title: Define the goal-to-plan copilot architecture
status: completed
phase: 12
depends_on:
  - LIFEOS-1109
  - LIFEOS-300
  - LIFEOS-114
risk: high
---

# Goal

Define a safe, Obsidian-native copilot that helps turn a broad goal or emerging
intention into one or more reviewable medium-term plan options and a small set of
near-term actions.

# User outcome

The user can begin with an incomplete idea, clarify what matters through a guided
conversation, compare realistic plan options, and approve only the parts that
fit. The copilot must make planning easier without converting every interest
into an obligation.

# Scope

- Define the end-to-end flow from goal selection or capture through clarification,
  context assembly, plan-option generation, rolling-wave decomposition, capacity
  checks, review, proposal creation, and explicit application.
- Separate:
  - canonical goals, plans, and task records
  - deterministic readiness and capacity facts
  - agent-generated interpretations and plan options
  - durable proposals
  - disposable conversation and UI state
- Define versioned contracts for planning sessions, questions, answers, plan
  options, milestones, near-term actions, assumptions, alternatives, conflicts,
  explanations, and proposal handoff.
- Define how existing context packs, adaptive-planning evidence, reviews, study
  workloads, blockers, energy, motivation, available time, and active-plan load
  may inform suggestions.
- Define when the copilot should recommend clarifying, experimenting, parking,
  pausing, or declining to create a plan.
- Define the Obsidian workspace, bridge operations, agent boundary, proposal
  lifecycle, stale-write protection, recovery, and audit trail.
- Define privacy, context minimization, and provider-neutral model boundaries.
- Add accepted design decisions and update architecture and roadmap documents.

# Required design questions

- What minimum information makes a goal ready for plan generation?
- How does the copilot preserve long-term goals as directions rather than task
  warehouses?
- How many options should be generated, and how are meaningful tradeoffs shown?
- Which fields are deterministic, user-authored, agent-suggested, or derived?
- How are assumptions and missing information represented without fabricating
  certainty?
- How much distant work may be decomposed before rolling-wave planning becomes
  false precision?
- How are existing plans, commitments, hobbies, exercise, study, rest, and
  personal constraints considered without reducing them to productivity inputs?
- How does the user edit or reject individual milestones and actions before a
  proposal exists?
- Which context may be sent to a model, and how is sensitive or irrelevant
  material excluded?
- How does the copilot behave when no model is configured or the model output is
  invalid?
- How are duplicate plans, conflicting task IDs, stale goal notes, and concurrent
  Obsidian edits handled?

# Out of scope

- Automatically choosing the user's goals.
- Automatically applying plans or task changes.
- A general semantic knowledge-chat workspace.
- Calendar writes or minute-by-minute scheduling.
- Psychological, medical, or motivational diagnosis.
- Cloud accounts, cross-user planning, or social comparison.
- Replacing the deterministic daily planner with an agent-authored schedule.

# Required invariants

- Goals remain user-owned directions.
- The copilot may suggest zero plans when planning would be premature.
- Distant work stays coarse; only near-term work becomes actionable.
- Every generated item exposes its source, assumption, and rationale.
- Existing user-authored content is never silently rewritten.
- Consequential changes use the existing durable proposal lifecycle.
- The baseline and adaptive daily planners remain deterministic and authoritative
  for daily menu construction.
- Model-specific files or instructions are not required by the repository.
- Disabling or removing the copilot leaves valid Markdown goals and plans.

# Required deliverables

- Accepted design decisions for readiness, option generation, rolling-wave depth,
  context minimization, and proposal boundaries.
- A component, trust-boundary, and data-flow diagram.
- Versioned planning-session and plan-option schemas with examples.
- A decision table for clarify, experiment, plan, park, pause, and decline paths.
- Failure-mode and recovery tables.
- A sequenced implementation plan aligned with LIFEOS-1201 through LIFEOS-1211.

# Acceptance criteria

- Every downstream Phase 12 task can rely on stable data and trust boundaries.
- The design supports a complete workflow inside Obsidian after installation.
- The architecture remains provider-neutral and testable without a live model.
- Generated plans cannot bypass proposal approval or stale-write validation.
- The design explicitly protects hobbies, exercise, study, and rest from being
  treated merely as productivity resources.
- Internal Markdown links and diagrams validate.

# Validation commands

```bash
git diff --check
python -m pytest tests/project -q
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-011: Read before write
- DD-014: Context packs use multiple retrieval modes
- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-023: Tasks stay with plans
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
