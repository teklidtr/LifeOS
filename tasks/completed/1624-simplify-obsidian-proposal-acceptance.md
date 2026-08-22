---
id: LIFEOS-1624
title: Simplify Obsidian proposal acceptance
status: completed
phase: 16
depends_on:
  - LIFEOS-1614
  - LIFEOS-1623
risk: high
---

# Goal

Replace the exposed Submit, Approve, and Apply sequence in Obsidian with one
explicit **Accept changes** action while preserving the durable lifecycle,
review-digest binding, target-hash validation, and recovery behavior.

# Scope

- Add a Python-owned composite acceptance operation for draft, pending, and
  approved proposals.
- Bind one trusted UI confirmation to the exact reviewed proposal digest.
- Execute only the remaining submit, approve, and apply transitions in order,
  reloading and checking the digest between transitions.
- Stop safely at the last durable lifecycle state if a later transition fails.
- Keep low-level lifecycle operations available to existing non-UI callers.
- Show **Accept changes** in Obsidian instead of separate Submit, Approve, and
  Apply buttons; keep Reject for pending and approved proposals.
- Update confirmation copy, tests, architecture, decisions, and user manuals.
- Rebuild and install verified plugin artifacts in the configured vault.

# Out of scope

- Removing lifecycle states from canonical proposal metadata.
- Weakening application preflight, stale-target checks, ownership validation, or
  crash recovery.
- Adding MCP auto-acceptance or changing ingestion's draft-only behavior.
- Automatically accepting proposals without an interactive confirmation.
- Deleting rejected or applied proposal history.

# Acceptance criteria

- Draft, pending, and approved proposals expose one **Accept changes** action.
- One confirmation applies an unchanged valid proposal and ends in `applied`.
- The confirmation is bound to the reviewed digest and cannot be reused.
- A changed proposal or stale target fails closed; any completed lifecycle step
  remains durable and visible.
- Existing low-level Submit, Approve, Reject, and Apply bridge behavior remains
  available for compatibility.
- Focused Python and plugin tests, full suites, typecheck, build, artifact tests,
  installed-artifact comparisons, manual links, and diff checks pass.

# Validation

```bash
uv run pytest -q tests/desktop/test_proposals.py
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
cmp packages/obsidian-plugin/build/main.js /Users/alwaysprep/LifeOS-vault/.obsidian/plugins/lifeos/main.js
cmp packages/obsidian-plugin/build/styles.css /Users/alwaysprep/LifeOS-vault/.obsidian/plugins/lifeos/styles.css
python scripts/validate_manual_links.py
git diff --check
```

# Relevant decisions

- DD-003: Durable proposal mode.
- DD-004: Proposal application is explicit.
- DD-031: Git-tracked proposals and stable layout.
- DD-034: Proposal validation remains deterministic.
- DD-036: Python owns proposal business semantics.
- DD-037: The plugin remains a thin client.
- DD-080: Obsidian acceptance uses one composite confirmation.

# Implementation record

- Added a Python-owned composite acceptance operation authorized once against
  the exact reviewed digest.
- Kept canonical draft, pending, approved, and applied states; the composite
  operation persists and reloads each remaining transition before continuing.
- Preserved application-time preflight, target-hash, ownership, locking,
  rollback, and recovery behavior.
- Replaced separate Submit, Approve, and Apply buttons with **Accept changes**
  for draft, pending, and approved proposals.
- Added one explicit acceptance confirmation explaining the digest and target
  checks; low-level lifecycle actions remain available through the bridge.
- Refreshes proposal state after a failed composite action so a durable pending
  or approved intermediate state is immediately visible.
- Recorded DD-080 and updated architecture and user manuals.
- Rebuilt and installed the verified Obsidian plugin artifacts.

# Validation record

- Focused desktop proposal tests: 8 passed.
- Focused facade tests: 34 passed.
- Focused bridge tests: 7 passed.
- Python Ruff and strict mypy checks: passed.
- Full Python suite: 1405 passed using importlib collection; the Unix-socket
  integrity case passed separately outside the filesystem sandbox.
- Obsidian plugin typecheck and lint: passed.
- Obsidian plugin tests: 52 passed.
- Production plugin build and 2 artifact tests: passed.
- Installed `main.js` and `styles.css` match the verified build byte-for-byte.
- Manual links and `git diff --check`: passed.
