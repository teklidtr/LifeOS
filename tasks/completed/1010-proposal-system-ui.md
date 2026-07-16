---
id: LIFEOS-1010
title: Add proposal review and system-health UI to Obsidian
status: backlog
phase: 10
depends_on:
  - LIFEOS-1002
  - LIFEOS-1003
  - LIFEOS-1004
risk: high
---

# Goal

Expose consequential proposal review and system diagnostics in Obsidian without
weakening authorization, recovery, integrity, or status semantics.

# Scope

- Add proposal lists grouped by lifecycle state.
- Show proposal rationale, sources, targets, exact typed operations, base hashes,
  review digest, and validation findings.
- Add side-by-side or unified previews appropriate to each patch operation.
- Provide **Submit**, **Approve**, **Reject**, and **Apply** actions through the
  trusted Python authorization boundary.
- Require explicit confirmation for approval and application.
- Refresh proposal state after external edits and reject stale review sessions.
- Add a System view for typed status diagnostics, recovery state, graph/export
  freshness and integrity, and bridge/plugin versions.
- Provide safe actions such as rebuild derived products or invoke an explicitly
  supported recovery operation.
- Preserve detailed error codes and remediation guidance.

# Out of scope

- Automatic approval or application.
- Editing proposal JSON directly in the UI.
- Hiding validation failures to simplify the interface.
- A remote administration dashboard.
- Broad arbitrary repair actions.

# Required invariants

- The plugin cannot supply its own approval digest or impersonate another actor.
- Approval never bypasses application-time validation.
- The exact reviewed content is bound to the approval.
- Read-only status inspection remains read-only.
- Recovery and rebuild actions are explicit and scoped.
- User-facing errors do not expose sensitive host paths or raw tracebacks.

# Required tests

- Full draft-to-applied flow through the plugin against a fixture vault.
- Rejection and stale proposal behavior.
- Proposal changes after review invalidate approval UI state.
- Failed authorization and cancelled confirmation.
- Application interruption and recovery presentation.
- Corrupt graph/export and unsupported-generation diagnostics.
- Bridge disconnect during consequential action.
- Keyboard-accessible diff and confirmation flows.

# Acceptance criteria

- A user can safely review and apply a proposal without opening the terminal.
- Existing proposal, authorization, recovery, and integrity services remain the
  authoritative implementation.
- System diagnostics remain typed and actionable.
- Python and plugin tests pass.

# Validation commands

```bash
pytest tests/proposals tests/facade tests/status tests/integration tests/e2e -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
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
- DD-035: Durable generated ownership
