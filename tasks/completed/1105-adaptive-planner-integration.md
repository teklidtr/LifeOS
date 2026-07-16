---
id: LIFEOS-1105
title: Integrate learned evidence into daily planning
status: completed
phase: 11
depends_on:
  - LIFEOS-1102
  - LIFEOS-1103
  - LIFEOS-1104
risk: high
---

# Goal

Use duration calibration, capacity-fit evidence, and avoidance diagnostics to
improve the daily menu while keeping the bounded planner deterministic,
explainable, optional, and subordinate to explicit user intent.

# Scope

- Add an adaptive planning policy layered on top of the existing bounded
  optimizer.
- Preserve the current planner as a baseline and safe fallback.
- Apply bounded adjustments for:
  - calibrated duration
  - capacity fit
  - motivation fit
  - repeated avoidance requiring clarification
  - estimate uncertainty
  - evidence freshness and quality
- Define hard caps so feedback cannot overwhelm due dates, blockers, explicit
  priorities, available time, or user-selected modes.
- Support `off`, `shadow`, and `active` adaptive modes.
- In shadow mode, compute and store comparison diagnostics without changing the
  selected menu.
- Return both baseline and adaptive results with typed deltas.
- Preserve deterministic output under shuffled input and equivalent evidence.
- Add versioned policy configuration and compatibility handling.

# Out of scope

- Automatic canonical plan edits.
- Calendar scheduling.
- Agent-authored daily menus.
- Reinforcement learning or hidden model weights.
- Cross-user recommendations.

# Required invariants

- The nonadaptive planner remains available and behaviorally stable.
- Blocked or completed tasks cannot be revived by feedback.
- Explicit user constraints always outrank learned preferences.
- Sparse, corrupt, disabled, or unavailable feedback produces baseline behavior.
- Every changed selection has a reproducible explanation.
- Repeated avoidance may lower eligibility or request clarification, but cannot
  silently cancel work.
- Running the planner remains read-only.

# Required tests

- No evidence produces exact baseline behavior.
- Shadow mode records differences but returns the baseline menu.
- Active mode with duration, fit, and avoidance adjustments.
- Caps and priority ordering.
- Contradictory feedback and low-confidence fallback.
- Disabled dimensions and full reset.
- Determinism under shuffled tasks, plans, and observations.
- Capacity constraints remain satisfied after calibration.
- Explanation/result compatibility across policy versions.
- Performance with realistic and large candidate sets.

# Acceptance criteria

- Adaptive menus fit observed reality better without becoming opaque.
- The planner exposes baseline, adjustment, and final decision evidence.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/planning_feedback tests/planning tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-023: Tasks stay with plans
- DD-025: Energy and motivation are distinct
- DD-027: Skipped tasks trigger diagnosis
- DD-033: SQLite disposability and rebuilding
