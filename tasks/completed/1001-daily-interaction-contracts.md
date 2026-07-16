---
id: LIFEOS-1001
title: Add typed daily-interaction contracts and mutation primitives
status: backlog
phase: 10
depends_on:
  - LIFEOS-1000
risk: high
---

# Goal

Create the typed Python application boundary needed by the Obsidian plugin for
safe daily reads and direct user-authorized writes without routing ordinary
interactions through ad hoc YAML editing or duplicating logic in TypeScript.

# Scope

- Define request and result models for:
  - quick capture
  - journal check-in updates
  - task outcome recording
  - task deferral and cancellation
  - review-note creation and update
- Define stable error types for validation, conflict, unavailable storage,
  blocked recovery, and unsupported operation.
- Require expected content hashes or equivalent optimistic-concurrency tokens
  for updates to existing canonical notes.
- Add idempotency keys for retryable user actions.
- Provide secure, atomic Markdown mutation primitives that preserve unrelated
  user-owned text and frontmatter fields.
- Reuse the existing parser, secure vault traversal, atomic-write, and recovery
  facilities instead of creating plugin-specific filesystem code.
- Return updated canonical references and deterministic read models suitable for
  immediate UI refresh.
- Define audit metadata for direct human actions without pretending that the
  SQLite registry is canonical history.

# Out of scope

- Network or JSON-RPC transport.
- Obsidian UI components.
- Agent-generated changes.
- Automatic task inference.
- Background scheduling.
- Generic unrestricted Markdown editing APIs.

# Required invariants

- Direct user actions are distinguishable from agent proposals.
- A stale UI cannot overwrite a note changed in Obsidian after it was read.
- Retrying the same idempotent request does not duplicate a capture or event.
- Unknown fields and invalid enum values fail closed.
- Human-owned prose outside explicitly targeted structures is preserved.
- Multi-file operations are either crash-consistent or redesigned to have one
  canonical write and derived follow-up work.

# Required tests

- Create capture succeeds and returns a stable canonical reference.
- Duplicate idempotency key returns the original result.
- Stale expected hash rejects an update without changing the target.
- Concurrent direct Obsidian edit is preserved.
- Invalid task ID, metric, date, enum, and path fail with typed errors.
- Interrupted write has a deterministic recovery outcome.
- Direct human mutation cannot invoke proposal approval or application paths.

# Acceptance criteria

- The plugin can use one typed Python boundary for all Phase 10 writes.
- No TypeScript-specific persistence rules are required.
- Conflict and retry semantics are explicit and tested.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/daily tests/facade tests/markdown tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-011: Read before write
- DD-012: Preservation checks are scripted
- DD-033: SQLite disposability and rebuilding
