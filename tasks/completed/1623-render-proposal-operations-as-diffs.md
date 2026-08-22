---
id: LIFEOS-1623
title: Render proposal operations as reviewable diffs
status: completed
phase: 16
depends_on:
  - LIFEOS-1614
  - LIFEOS-1622
risk: medium
---

# Goal

Replace raw operation JSON in the Obsidian proposal workspace with a GitHub-style
diff review that makes removed lines red and added lines green.

# Scope

- Expose deterministic, read-only unified-diff previews for proposal operations
  through the existing desktop proposal inspection service.
- Preserve typed patch JSON as the canonical operation format and preserve the
  existing review digest and lifecycle behavior.
- Render operation type and target metadata without dumping raw JSON.
- Render file headers, hunk headers, context, removed, and added lines with
  accessible semantic classes and Obsidian-theme-compatible colors.
- Cover created files and exact human-file patches used by compound ingestion,
  while degrading safely when an exact replacement preview cannot be produced.
- Rebuild and install the verified plugin artifacts in the configured vault.

# Out of scope

- Changing proposal schemas, operation application, validation, or lifecycle.
- Editing `patches.json` from the plugin.
- Adding an interactive diff editor.
- Redesigning unrelated Obsidian workspaces.

# Acceptance criteria

- The proposal workspace no longer renders operation objects as JSON.
- Created-file contents render as added lines and human-file patch deletions and
  additions render as red and green diff rows.
- Context and hunk/header lines remain visually distinct and long lines wrap
  without escaping the proposal detail pane.
- Operation order, type, and target path remain visible.
- Missing or stale replacement targets produce an explicit preview-unavailable
  message instead of hiding the proposal or breaking the workspace.
- Focused desktop and plugin tests, typecheck, production build, artifact test,
  installed-artifact comparisons, and diff checks pass.

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
git diff --check
```

# Relevant decisions

- DD-031: Git-tracked proposals and stable layout.
- DD-032: Typed JSON patches remain canonical.
- DD-034: Proposal validation remains deterministic.
- DD-036: Obsidian is the primary interface and Python owns proposal semantics.
- DD-037: The plugin remains a thin client over the desktop bridge.

# Implementation record

- Replaced raw JSON operation inspection with a Python-produced, read-only
  unified-diff preview contract that preserves operation order, type, and target.
- Added exact previews for created files and human patches, plus base-hash-bound
  previews for generated-file and managed-block replacements.
- Added safe preview-unavailable results for missing, stale, malformed, or
  unsupported replacement targets without hiding the proposal.
- Added a line-number-aware TypeScript diff parser and an Obsidian renderer for
  file headers, hunk headers, context, added, removed, and note rows.
- Added responsive red/green diff styling and updated the proposal-review user
  documentation.
- Rebuilt the plugin and copied the verified JavaScript and stylesheet into the
  configured LifeOS vault.

# Validation record

- Focused desktop proposal tests: 5 passed.
- Python Ruff and strict mypy checks: passed.
- Full Python suite: 1402 passed using importlib collection; the socket integrity
  case passed separately outside the filesystem sandbox.
- Obsidian plugin typecheck and lint: passed.
- Obsidian plugin tests: 51 passed.
- Production plugin build: passed.
- Artifact tests: 2 passed.
- Installed `main.js` and `styles.css` match the verified build byte-for-byte.
- Manual links and `git diff --check`: passed.
- The active compound ingestion proposal produced two usable diff previews with
  no preview errors.
