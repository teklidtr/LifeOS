---
id: LIFEOS-1602
title: Add storage lifecycle extraction and processing
status: ready
phase: 16
depends_on:
  - LIFEOS-1601
risk: high
---

# Goal

Content-addressed storage, deduplication, references, lifecycle transitions, local extraction, resumable jobs, merge and split.

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

- Recorded at completion.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-074 through DD-078
- Rich Capture Architecture
