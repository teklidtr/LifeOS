---
id: LIFEOS-1101
title: Build the execution feedback evidence dataset
status: completed
phase: 11
depends_on:
  - LIFEOS-1100
  - LIFEOS-1006
  - LIFEOS-1007
risk: high
---

# Goal

Transform canonical task-outcome and reconciliation records into a deterministic,
versioned, rebuildable evidence dataset suitable for adaptive planning.

# Scope

- Read execution records created by LIFEOS-1006 and reconciled outcomes created
  through LIFEOS-1007.
- Normalize observations for:
  - task, plan, and goal identity
  - planned and actual duration
  - outcome and completion fraction
  - start and end time when explicitly recorded
  - energy and motivation before and after
  - task mode and task-shape metadata
  - blockers and skip, defer, or partial-completion reasons
  - source record and correction lineage
- Represent missing, unknown, disabled, and not-applicable values distinctly.
- Reject or diagnose duplicate IDs, impossible durations, invalid chronology,
  orphaned task references, conflicting corrections, and unsupported schema
  versions.
- Add deterministic feature extraction and stable observation IDs.
- Store only rebuildable query state under `.lifeos/` or the disposable registry.
- Add incremental rebuilding based on canonical content hashes.
- Add typed dataset status and diagnostics.
- Expose read-only facade and bridge operations needed by later planner and UI
  tasks.

# Out of scope

- Calculating duration calibration.
- Ranking planner candidates.
- Diagnosing avoidance.
- Writing corrections to canonical history from this task.
- Inferring task completion from note activity or timers without confirmation.

# Required invariants

- Every observation traces to canonical source evidence.
- Rebuilding from the same vault produces byte-for-byte equivalent derived data.
- Corrections supersede earlier records without erasing their lineage.
- Unknown outcomes remain unknown.
- Invalid records are surfaced through typed diagnostics, not silently dropped.
- Deleting the derived dataset does not lose canonical execution history.
- Feature extraction never reads private data outside the configured planning
  scope.

# Required tests

- Empty history and a single complete outcome.
- Partial, skipped, deferred, cancelled, and unaccounted reconciliation records.
- Missing energy, motivation, actual duration, and reason fields.
- Corrected and retracted records.
- Duplicate IDs and conflicting correction chains.
- Task renamed, moved between plans, archived, or deleted after execution.
- Timezone, DST, midnight, and clock-skew cases.
- Incremental rebuild versus clean rebuild equivalence.
- Unsupported schema and malformed canonical records.
- Determinism under shuffled filesystem and registry ordering.

# Acceptance criteria

- Later feedback modules consume one typed evidence API rather than scanning raw
  notes independently.
- Dataset status explains counts, exclusions, corrections, and diagnostics.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/execution tests/planning_feedback tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-023: Tasks stay with plans
- DD-025: Energy and motivation are distinct
- DD-030: Scope-local logs are generated views
- DD-033: SQLite disposability and rebuilding
