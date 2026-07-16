---
id: LIFEOS-1007
title: Add an attention engine and unaccounted-outcome reconciliation
status: backlog
phase: 10
depends_on:
  - LIFEOS-1004
  - LIFEOS-1006
risk: high
---

# Goal

Make LifeOS notice missing updates and unresolved daily loops without assuming
that silence means failure or requiring the user to prompt an agent manually.

# Scope

- Add a deterministic attention engine that produces typed, explainable items.
- Detect at least:
  - a planned action with no recorded outcome after its review window
  - a missing morning or evening check-in
  - an unfinished study session
  - a plan with no eligible next action
  - an inbox item older than a configured threshold
  - repeated unaccounted days
  - an active experiment missing required observations
- Represent `unaccounted` as a computed condition unless an accepted design
  decision requires canonical persistence.
- Add stable attention-item IDs, severity, evidence, first-seen time, suggested
  actions, and expiry rules.
- Add dashboard reconciliation cards with **Done**, **Partial**, **Skipped**,
  **Deferred**, **No longer relevant**, **Ask tomorrow**, and **Dismiss**.
- Persist snooze, dismissal, and routine-frequency preferences in an explicitly
  defined durable or disposable location.
- Keep rules deterministic; invoke an agent only through a later proposal or
  diagnosis workflow.
- Prevent repetitive reminders from multiplying across refreshes.

# Out of scope

- Operating-system notifications while Obsidian is closed; LIFEOS-1011 covers
  that delivery channel.
- Inferring completion from note edits without confirmation.
- Punitive streaks or productivity scoring.
- Automatic task rescheduling.
- LLM calls for ordinary attention detection.

# Required invariants

- Absence of evidence is labeled unknown or unaccounted, never skipped.
- Every attention item shows why it exists and which canonical evidence supports
  it.
- Read-only attention evaluation does not create or mutate canonical notes.
- Snoozed or dismissed items behave deterministically.
- A resolved underlying condition removes the item without manual cleanup.
- Quiet periods and disabled routines are respected.

# Required tests

- Planned action with no outcome becomes unaccounted at the correct boundary.
- Explicit outcome prevents the attention item.
- Late outcome resolves an existing item.
- Clock, timezone, DST, and date-boundary cases.
- Repeated evaluation yields stable IDs and no duplicates.
- Snooze, dismiss, expiry, and preference changes.
- Missing journal versus intentionally disabled check-in.
- Multiple independent attention items survive one subsystem failure.

# Acceptance criteria

- LifeOS proactively surfaces missing stories in the Today dashboard.
- The system never equates silence with failure.
- Reconciliation actions reuse LIFEOS-1006 rather than implementing parallel
  writes.
- Full tests, Ruff, mypy, and plugin checks pass.

# Validation commands

```bash
pytest tests/attention tests/daily tests/planning tests/study tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-025: Energy and motivation are distinct
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
- DD-033: SQLite disposability and rebuilding
