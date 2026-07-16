---
id: LIFEOS-1102
title: Calibrate task-duration estimates from execution evidence
status: completed
phase: 11
depends_on:
  - LIFEOS-1101
risk: medium
---

# Goal

Use completed and partially completed execution evidence to produce cautious,
explainable duration forecasts without overwriting the user's declared estimate.

# Scope

- Add deterministic duration calibration using robust statistics.
- Support hierarchical evidence levels such as:
  - recurring task identity
  - task shape or template
  - plan
  - work mode
  - global personal baseline
- Define minimum sample sizes and bounded fallback behavior.
- Report original estimate, calibrated estimate, evidence level, sample count,
  spread, freshness, outliers, and confidence.
- Treat partial outcomes carefully and exclude records lacking interpretable
  progress or duration.
- Add configurable caps so sparse history cannot produce extreme adjustments.
- Detect systematic underestimation and overestimation by mode or task shape.
- Preserve historical forecasts for reproducible planner explanations.
- Expose read-only APIs for planners, reviews, and Obsidian views.

# Out of scope

- Editing duration fields in plan notes.
- Predicting completion probability.
- Inferring time from Obsidian activity without explicit confirmation.
- Neural or black-box regression models.
- Cross-user estimates.

# Required invariants

- The user's estimate remains visible and authoritative in the plan note.
- Calibration is advisory and can be disabled.
- Sparse, stale, or contradictory evidence falls back to the declared estimate.
- Extreme observations cannot dominate the forecast silently.
- Every forecast includes a reproducible evidence explanation.
- A reset removes derived calibration without deleting execution history.

# Required tests

- No evidence, one sample, threshold boundary, and sufficient samples.
- Consistent underestimation and overestimation.
- Exact-task, plan, mode, and global fallback ordering.
- Partial completion and interrupted sessions.
- Zero, negative, impossible, and extreme durations.
- Recent evidence versus stale evidence.
- Shuffled observation order and deterministic rounding.
- Disabled calibration and reset behavior.
- Planner compatibility when calibration is unavailable or corrupt.

# Acceptance criteria

- Duration forecasts improve capacity accounting while preserving safe fallback.
- Explanations show why a forecast differs from the declared estimate.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/planning_feedback/test_duration_calibration.py tests/planning tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-023: Tasks stay with plans
- DD-025: Energy and motivation are distinct
- DD-033: SQLite disposability and rebuilding
