---
id: LIFEOS-1210
title: Integrate the copilot with goal reviews and rolling replanning
status: completed
phase: 12
depends_on:
  - LIFEOS-1108
  - LIFEOS-1208
  - LIFEOS-1209
risk: high
---

# Goal

Let the user revisit goals and plans with the same copilot when reality changes,
without erasing prior intent or endlessly rescheduling stale work.

# Scope

- Add guided review entry points for goals with no active plan, plans with no
  feasible next action, completed milestones, repeated avoidance, changed
  constraints, stale assumptions, and approaching review dates.
- Compare the original plan option, current canonical plan, execution evidence,
  explicit corrections, and recent review answers.
- Offer review outcomes: continue unchanged, adjust next wave, revise scope,
  split, merge, pause, supersede, close, return to experiment, or reopen goal
  clarification.
- Generate only reviewable proposals for consequential changes.
- Preserve supersession and decision lineage.
- Prevent rejected suggestions from reappearing unchanged without new evidence.
- Integrate with daily attention and weekly review views.

# Out of scope

- Automatic replanning after every missed task.
- Declaring a goal invalid based on planner evidence.
- Psychological diagnosis.
- Deleting historical plans or execution evidence.

# Required invariants

- Replanning begins from current canonical state, not an old session snapshot.
- Execution evidence may prompt questions but cannot rewrite intent.
- Repeated avoidance leads to clarification, decomposition, pausing, or goal
  review rather than endless date changes.
- Superseded plans remain traceable.
- The user may continue unchanged.

# Required tests

- Goal without active plan and plan without next action.
- Completed milestone and next-wave generation.
- Changed deadline, scope, capacity, and prerequisite.
- Repeated avoidance with competing explanations.
- Continue unchanged, pause, supersede, close, and reopen paths.
- Rejected suggestion suppression and reappearance after new evidence.
- Stale source during review and interrupted proposal application.
- Daily attention and weekly review integration.

# Acceptance criteria

- The copilot supports planning as a living review loop rather than one-time plan
  generation.
- Historical intent and decisions remain inspectable.
- Full Python and TypeScript suites, lint, type checks, and builds pass.

# Validation commands

```bash
pytest tests/reviews tests/attention tests/planning tests/planning_feedback tests/proposals tests/e2e -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
