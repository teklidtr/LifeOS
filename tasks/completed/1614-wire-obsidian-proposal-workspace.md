---
id: LIFEOS-1614
title: Wire the Obsidian proposal workspace
status: completed
phase: 16
depends_on:
  - LIFEOS-1010
  - LIFEOS-1612
risk: high
---

# Goal

Expose the existing proposal review controller and bridge lifecycle through the
loadable Obsidian plugin so proposals can be reviewed and acted on without a
terminal.

# Scope

- Register a dedicated LifeOS Proposals view and command-palette entry.
- Load and group proposals by lifecycle state.
- Inspect proposal rationale, body, sources, operations, digest, and findings.
- Expose Submit, Approve, Reject, and Apply through the existing digest-bound
  `proposal.prepare` and `proposal.execute` bridge flow.
- Require explicit interactive confirmation and refresh after lifecycle actions.
- Render clear loading, empty, error, stale-review, and action-result states.
- Add focused controller, plugin wiring, and rendering tests.
- Correct user documentation only if it does not match the shipped entry point.

# Out of scope

- Changing Python proposal semantics or authorization.
- Adding proposal lifecycle methods to MCP.
- Editing proposal JSON in the plugin.
- Automatic submission, approval, or application.
- Reworking unrelated Obsidian workspaces.

# Acceptance criteria

- The command palette opens a dedicated LifeOS Proposals view.
- The view lists proposals and displays the full selected inspection returned by
  the bridge.
- Every consequential action uses the existing confirmation challenge and rejects
  a proposal whose digest changed after review.
- Successful and failed actions refresh visible state without bypassing Python.
- Plugin tests, typecheck, production build, artifact smoke test, and diff checks
  pass.

# Validation commands

```bash
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
git diff --check
```

# Relevant design decisions

- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-031: Git-tracked proposals and stable layout
- DD-034: Proposal validation
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-037: The default desktop transport is a vault-scoped STDIO child process
