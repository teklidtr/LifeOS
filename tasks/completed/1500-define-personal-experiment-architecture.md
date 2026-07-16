---
id: LIFEOS-1500
title: Define personal experiment architecture
status: completed
phase: 15
depends_on:
  - LIFEOS-1411
risk: high
---

# Goal

Audit the repository and define the complete Direction 6 task sequence, ownership boundaries, safety model, recovery model, and UI-first architecture.

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

- Architecture and task-convention checks.
- Dependency, duplication, privacy, migration, accessibility, and performance review.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

- Repository architecture, roadmap, task conventions, canonical artifact ownership, proposal safety, provider neutrality, migration, privacy, accessibility, and performance risks were audited before implementation.
- `git diff --check`: passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
