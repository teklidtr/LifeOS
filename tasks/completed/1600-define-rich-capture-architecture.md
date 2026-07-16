---
id: LIFEOS-1600
title: Define rich capture architecture
status: completed
phase: 16
depends_on:
  []
risk: high
---

# Goal

Architecture, dependency audit, storage and privacy decisions, and sequenced task design.

# Scope

- Implement only this task's named capability and focused tests.
- Preserve canonical Markdown, original bytes, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record explicit degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to external canonical artifacts.

# Required invariants

- Markdown and original attachment bytes remain canonical and portable.
- Unknown and missing values never become zero.
- Estimates remain distinct from confirmed facts.
- Derived state can be deleted and rebuilt.
- Protected content is not sent externally without explicit inspectable intent.

# Required tests

- Focused deterministic fixtures for this task, including degraded and stale states.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

- `python3 scripts/validate_manual_links.py`: existing 13 chapters validated.
- `git diff --check`: passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-074 through DD-078
- Rich Capture Architecture
