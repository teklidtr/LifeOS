---
id: LIFEOS-1006
title: Record task outcomes and execution history from Obsidian
status: backlog
phase: 10
depends_on:
  - LIFEOS-1001
  - LIFEOS-1004
  - LIFEOS-1005
risk: high
---

# Goal

Allow the user to record what happened to a planned action and preserve enough
canonical evidence for later adaptation without forcing a simplistic done/not
done model.

# Scope

- Support explicit outcomes:
  - started
  - done
  - partial
  - skipped
  - deferred
  - cancelled
- Record optional planned minutes, actual minutes, energy before and after,
  motivation before, difficulty, satisfaction, reason, and free-text note.
- Define the canonical relationship between plan task state and dated execution
  history, avoiding two conflicting sources of truth.
- Add Today dashboard controls such as **Start**, **Complete**, **Partial**,
  **Skip**, **Defer**, **Cancel**, and **Record time**.
- Preserve repeated attempts as history while keeping the current task state
  easy to read from the plan.
- Add deterministic normalization and indexing for later planner calibration.
- Require a reason only where useful; do not make every interaction a form-filling
  ceremony.
- Link an execution record back to its plan, task ID, date, and optional study or
  source artifact.

# Out of scope

- Learning planner weights from history.
- Calendar time tracking.
- Passive surveillance of open notes.
- Automatically treating silence as skipped.
- Agent interpretation of avoidance.

# Required invariants

- Historical attempts are append-preserving and traceable.
- Current task state and execution history cannot silently disagree.
- Duplicate UI submission does not create duplicate history.
- `partial`, `skipped`, `deferred`, and `cancelled` remain distinct.
- Direct user outcomes are not rewritten by an agent.
- Existing plan and journal prose are preserved.

# Required tests

- Every outcome transition from a valid task state.
- Illegal transitions and updates to missing tasks.
- Multiple attempts across dates.
- Partial completion followed by completion.
- Defer with and without a new date.
- Duplicate submit and stale plan conflict.
- Cross-midnight timer or elapsed-time entry.
- Rebuilding disposable indexes from canonical history.

# Acceptance criteria

- The dashboard can close the loop on a selected task in two clicks for the
  common case.
- Richer evidence is available without being mandatory.
- Canonical history survives registry deletion and plugin reinstallation.
- Full tests, Ruff, mypy, and plugin checks pass.

# Validation commands

```bash
pytest tests/daily tests/planning tests/registry tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-021: Adaptive planning, not conventional task management
- DD-023: Tasks stay with plans
- DD-025: Energy and motivation are distinct
- DD-027: Skipped tasks trigger diagnosis
- DD-033: SQLite disposability and rebuilding
