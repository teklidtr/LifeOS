---
id: LIFEOS-1502
title: Add experiment design safety and schedules
status: completed
phase: 15
depends_on:
  - LIFEOS-1501
risk: high
---

# Goal

Implement inspectable design warnings, blocking safety classification, timezone-safe schedules, and provider-neutral optional assistance contracts with no-model fallback.

# Scope

- Implement only this task's named capability and its focused tests.
- Preserve canonical Markdown, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record diagnostics and degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to goals, plans, habits, tasks, metrics, notes, reminders, or calendars.

# Required invariants

- Markdown remains canonical and portable.
- Missing observations never become zero.
- Derived state can be deleted and rebuilt.
- Unsafe experiments fail closed before scheduling or activation.
- Descriptive evidence never produces a causal claim.

# Required tests

- Vague protocol, confounder, duplicate, overlap, unsafe, emergency, cadence, timezone, timeout, malformed-output, and no-model fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

- `PYTHONPATH=src python3 -m pytest -q tests/experiments/test_design_safety_schedule.py`: 4 passed.
- `git diff --check`: passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
