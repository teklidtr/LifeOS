---
id: LIFEOS-1508
title: Validate and document personal experiments
status: ready
phase: 15
depends_on:
  - LIFEOS-1507
risk: high
---

# Goal

Complete user documentation, protocol and schema documentation, end-to-end validation, change reports, clean-tree checks, and release packaging.

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

- Full Python/plugin regression, lint, typecheck, build, links, provider-neutrality, rebuild, migration, and packaging validation.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands


tbd during implementation

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
