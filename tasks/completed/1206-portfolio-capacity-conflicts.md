---
id: LIFEOS-1206
title: Check portfolio capacity, conflicts, and plan fit
status: completed
phase: 12
depends_on:
  - LIFEOS-1205
  - LIFEOS-1105
risk: high
---

# Goal

Show whether a proposed plan fits alongside existing commitments before the user
accepts it, without collapsing life into a single productivity score.

# Scope

- Compare proposed milestones and near-term actions with active plans, known due
  dates, blocked work, recurring study workloads, explicit routines, and stated
  capacity constraints.
- Use baseline estimates and optional adaptive duration evidence while preserving
  both views.
- Detect overload, mutually exclusive timing, duplicate outcomes, competing
  prerequisites, no feasible next action, and excessive active-plan count.
- Present conflicts as inspectable findings with severity, evidence, missingness,
  and possible adjustments.
- Generate alternatives such as reduce scope, extend horizon, pause another plan,
  run an experiment, or keep the goal unplanned.
- Expose read-only facade and bridge operations.

# Out of scope

- Selecting which existing plan to sacrifice.
- Creating a universal life score.
- Inferring calendar availability from unconnected sources.
- Automatically changing priorities, due dates, or plan status.

# Required invariants

- Missing capacity data is not treated as zero capacity.
- Adaptive evidence is optional and the baseline remains visible.
- Hobbies, exercise, diet, rest, and relationships are not treated as expendable
  slack.
- Conflict findings create choices, not commands.
- The check is deterministic for equivalent inputs.

# Required tests

- Fits comfortably, marginal fit, overload, and unknown capacity.
- Conflicting due dates and prerequisites.
- Duplicate outcomes across plans.
- Baseline versus adaptive estimate differences.
- Disabled or corrupt feedback data.
- No active plans and many active plans.
- Missing recurring-workload data.
- Stable findings under shuffled inputs.

# Acceptance criteria

- The user can see what the new plan would displace or strain before approval.
- No aggregate output masquerades as an objective productivity or life score.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/planning tests/planning_feedback tests/study tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-033: SQLite disposability and rebuilding
