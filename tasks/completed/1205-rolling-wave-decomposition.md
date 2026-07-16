---
id: LIFEOS-1205
title: Decompose selected plans with rolling-wave depth
status: completed
phase: 12
depends_on:
  - LIFEOS-1204
  - LIFEOS-500
risk: high
---

# Goal

Turn a selected plan option into coarse milestones and a deliberately small set
of concrete next actions without pretending that distant work is predictable.

# Scope

- Define decomposition depth rules by horizon, uncertainty, dependency, and
  review cadence.
- Keep distant milestones outcome-oriented and decompose only the current wave
  into actionable plan tasks.
- Generate task fields compatible with the existing planner: duration, energy,
  motivation, mode, due date when justified, blockers, and plan ownership.
- Detect actions that are too vague, too large, duplicated, blocked, or not
  independently verifiable.
- Support study work as bounded sessions rather than one task per flashcard.
- Add explicit checkpoints for re-decomposition after milestone review.
- Preserve editable rationale and source references for every generated item.

# Out of scope

- Building a minute-by-minute schedule.
- Decomposing an entire long-term goal into a complete backlog.
- Automatically marking tasks active or completed.
- Generating flashcard content.

# Required invariants

- Only near-term work becomes small actions.
- Tasks stay inside the selected plan.
- No task receives fabricated precision.
- Due dates are omitted unless supported by an external or user-defined
  constraint.
- Study, exercise, rest, and hobbies may be legitimate outcomes or activities,
  not merely means to increase output.
- Generated task IDs are stable and collision-free before proposal creation.

# Required tests

- Short, medium, and uncertain plan horizons.
- One-step plans and multi-milestone plans.
- Oversized, vague, duplicate, blocked, and circular actions.
- Study sessions and flashcard-review workloads.
- Missing duration, energy, motivation, and mode estimates.
- Explicit deadlines versus invented deadlines.
- Re-decomposition after milestone completion or plan change.
- Determinism under shuffled option content.

# Acceptance criteria

- The result is immediately reviewable by the user and consumable by the daily
  planner after approval.
- Distant work remains coarse enough to revise honestly.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/planning tests/study tests/registry tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-023: Tasks stay with plans
- DD-024: Flashcards are workload sessions
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
