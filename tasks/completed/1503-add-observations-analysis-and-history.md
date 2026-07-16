---
id: LIFEOS-1503
title: Add observations analysis and history
status: completed
phase: 15
depends_on:
  - LIFEOS-1502
risk: high
---

# Goal

Implement explicit missing-state observations, deterministic descriptive analysis, chart-ready derived views, lineage-aware history, and rebuildable indexes.

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

- Baseline/intervention, qualitative, adherence, missing, skip, pause, insufficient, inconclusive, lineage, rename, deletion, duplicate, and large-history fixtures.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

....                                                                     [100%]
4 passed in 5.62s

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
