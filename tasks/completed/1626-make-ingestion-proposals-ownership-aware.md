---
id: LIFEOS-1626
title: Make ingestion proposals ownership-aware
status: completed
phase: 16
depends_on:
  - LIFEOS-1622
risk: high
---

# Goal

Prevent MCP ingestion from creating drafts whose operation type conflicts with
durable generated ownership, and define a bounded update route for an existing
generated-owned wiki note.

# Scope

- Check `system/generated-ownership.json` while building create, section-update,
  and compound ingestion proposals.
- Refuse an absent create target that still has a durable ownership entry with
  a specific remediation diagnostic.
- Never emit `patch_human_file` for a generated-owned target.
- Define and implement the bounded proposal operation used when ingestion must
  update a generated-owned wiki note.
- Cover facade, MCP, preflight, and user-facing guidance with tests.

# Out of scope

- Silently deleting or reconstructing durable ownership entries.
- Weakening target hashes or application-time ownership checks.
- Whole-vault ownership reconciliation.

# Acceptance criteria

- Every ingestion proposal emitted by MCP can pass ownership preflight when its
  targets remain unchanged.
- Generated-owned targets are never represented as human-file patches.
- Orphaned ownership produces a precise diagnostic and no unusable draft.

# Relevant decisions and policy

- DD-035: generated ownership is durable authorization state.
- DD-079: agent-assisted ingestion is MCP-only and bounded.
- DD-081: ingestion selects operations from canonical ownership before draft
  publication.
- `docs/safety-and-ownership.md`: fully generated files require matching
  ownership and human-owned content requires exact reviewable patches.

# Implementation record

- Required the canonical ownership manifest before any create, update, or
  compound ingestion draft is published.
- Refused an absent create or update target with a retained ownership entry and
  returned bounded restore-or-release remediation through MCP.
- Kept human-owned exact-section updates as `patch_human_file` operations.
- Added a bounded generated-owned route that verifies generator identity and
  the raw manifest hash, deterministically changes one exact section, and emits
  `replace_generated_file`.
- Applied the same classification to the update half of compound ingestion, so
  its ordered operations are create plus either human patch or generated
  replacement.
- Refused generator mismatches, external modifications, human managed-block
  targets, and missing or malformed ownership state before proposal
  persistence.
- Added DD-081, MCP instructions, safety guidance, architecture, and user-manual
  documentation.
- Recorded incremental multi-source generated-wiki provenance as LIFEOS-1628
  rather than expanding this task's ownership scope.

# Validation record

- Focused ingestion, facade, MCP, and lifecycle suites: 173 passed.
- Task-scoped Ruff: passed.
- Strict mypy across changed source files: passed.
- Full Python suite with importlib collection: 1416 passed; the sole Unix-socket
  case blocked by the filesystem sandbox passed separately outside the sandbox.
- Manual links and `git diff --check`: passed.
