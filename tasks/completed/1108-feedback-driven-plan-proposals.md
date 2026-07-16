---
id: LIFEOS-1108
title: Turn feedback into reviewable plan-improvement proposals
status: completed
phase: 11
depends_on:
  - LIFEOS-1009
  - LIFEOS-1010
  - LIFEOS-1104
  - LIFEOS-1105
  - LIFEOS-1106
risk: high
---

# Goal

Convert durable feedback patterns into explicit, reviewable proposals for better
plans instead of silently rewriting tasks or repeatedly rescheduling them.

# Scope

- Add weekly-review summaries for:
  - systematic duration error
  - repeatedly avoided or partial tasks
  - tasks with no feasible capacity window
  - plans with no eligible next action
  - recurring blockers
  - routines repeatedly dismissed or unaccounted
  - goals whose active plans appear stalled
- Add proposal types for:
  - update a task estimate
  - clarify or decompose a task
  - change task mode or capacity requirements
  - add or resolve a blocker
  - pause or resume a plan
  - revise a review date
  - reduce or disable a tracking routine
  - open a goal review
- Include exact evidence, alternative interpretations, confidence, and expected
  effect in every proposal.
- Reuse the existing proposal lifecycle, ownership rules, application state
  machine, recovery, and Obsidian proposal UI.
- Permit agent-assisted decomposition only after explicit user request and with a
  bounded context pack.
- Track accepted, rejected, and dismissed proposal outcomes as future feedback
  without treating rejection as user failure.

# Out of scope

- Automatic application or approval.
- Creating psychological or health conclusions.
- Rewriting long-term goals without explicit review.
- Generating large project plans from one diagnosis.
- Treating planner optimization as authority over user preference.

# Required invariants

- Statistical evidence can create only a proposal, never a canonical edit.
- Proposal patches read the latest target and use stale-write protection.
- Rejected proposals do not reappear unchanged without new evidence.
- Alternatives and uncertainty remain visible.
- Proposal application remains atomic and recoverable.
- The user may choose no action.

# Required tests

- Duration update, decomposition, blocker, pause, and routine-reduction proposals.
- Insufficient and contradictory evidence suppressing proposals.
- Duplicate proposal prevention and reappearance after meaningful new evidence.
- Target changed before approval or application.
- Rejected, dismissed, stale, and applied proposal feedback.
- Agent-assisted decomposition with bounded context and invalid output.
- UI review through approval, application, interruption, and recovery.
- No direct canonical mutation during analysis.

# Acceptance criteria

- Feedback produces useful plan improvements without bypassing human judgment.
- Existing proposal and recovery guarantees remain intact.
- Full Python and TypeScript suites, lint, type checks, and builds pass.

# Validation commands

```bash
pytest tests/planning_feedback tests/proposals tests/recovery tests/integration tests/e2e -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-011: Read before write
- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-027: Skipped tasks trigger diagnosis
- DD-034: Proposal validation
