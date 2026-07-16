---
id: LIFEOS-1606
title: Build Obsidian rich capture workspace
status: completed
phase: 16
depends_on:
  - LIFEOS-1605
risk: high
---

# Goal

Quick capture, review, gallery, timeline, queue, mobile, drag/drop, clipboard, and accessibility state models.

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

- `npm --prefix packages/obsidian-plugin test` -> 43 passed.
- `npm --prefix packages/obsidian-plugin run typecheck` -> passed.
- `npm --prefix packages/obsidian-plugin run lint` -> passed.
- `npm --prefix packages/obsidian-plugin run build` -> passed.
- `git diff --check` -> passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-074 through DD-078
- Rich Capture Architecture
