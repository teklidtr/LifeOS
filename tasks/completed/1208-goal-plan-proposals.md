---
id: LIFEOS-1208
title: Convert approved copilot drafts into safe goal and plan proposals
status: completed
phase: 12
depends_on:
  - LIFEOS-1205
  - LIFEOS-1207
  - LIFEOS-113
risk: high
---

# Goal

Turn only the user's selected and edited copilot output into durable, reviewable,
recoverable proposals for goal and plan files.

# Scope

- Add proposal types for creating a plan, linking a plan to a goal, updating
  selected goal fields, adding milestones, adding near-term tasks, and pausing or
  superseding an explicitly selected conflicting plan.
- Allow item-level inclusion, exclusion, and editing before proposal creation.
- Read current targets and record exact base hashes.
- Validate stable IDs, links, managed blocks, task ownership, duplicates,
  required fields, and preservation rules.
- Reuse proposal approval, stale detection, atomic application, recovery,
  indexing, generated ownership, and audit events.
- Link the planning session and selected option to the proposal without making
  session state canonical plan content.
- Ensure rejected or abandoned drafts remain distinguishable from applied plans.

# Out of scope

- Automatic proposal approval or application.
- Bulk rewriting all active plans.
- Applying a plan directly from model output.
- Treating a rejected option as user failure.

# Required invariants

- No canonical goal or plan changes occur before explicit proposal approval and
  deterministic application.
- Proposal patches are generated from the user's final visible draft.
- Concurrent edits fail closed as stale.
- Human-authored sections and unrelated tasks are preserved.
- Application is atomic and recoverable.
- Rejection does not silently alter future planner behavior.

# Required tests

- New plan creation and existing-goal linking.
- Selected goal-field update without unrelated rewrites.
- Milestone and task insertion into valid managed regions.
- Item-level exclusion and edited draft fields.
- Duplicate IDs, invalid links, stale targets, and concurrent edits.
- Interrupted application and recovery.
- Rejected, dismissed, stale, and applied lifecycle paths.
- Registry and index rebuilding after application.

# Acceptance criteria

- Copilot output reaches canonical Markdown only through the existing trusted
  proposal machinery.
- Full proposal, recovery, lint, type, and integration suites pass.

# Validation commands

```bash
pytest tests/proposals tests/recovery tests/planning tests/registry tests/integration tests/e2e -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-011: Read before write
- DD-012: Preservation checks are scripted
- DD-031: Git-tracked proposals and stable layout
- DD-032: Typed JSON patches
- DD-034: Proposal validation
