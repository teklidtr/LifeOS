---
id: LIFEOS-1621
title: Show proposal creation dates in Obsidian
status: completed
phase: 16
depends_on:
  - LIFEOS-1614
  - LIFEOS-1620
risk: low
---

# Goal

Make proposal age visible in the Obsidian proposal workspace so the user can
distinguish newer proposals from older ones at a glance.

# Scope

- Expose canonical proposal `created_at` through the existing desktop bridge.
- Show a locally formatted creation date and time on each proposal-list row and
  in the selected proposal metadata.
- Sort proposals newest-first within each lifecycle group, with deterministic
  title and ID tie-breakers.
- Add focused Python and TypeScript coverage and rebuild the plugin artifact.
- Copy verified plugin artifacts into the configured LifeOS vault.

# Out of scope

- Changing proposal lifecycle semantics or canonical timestamps.
- Adding inferred filesystem timestamps.
- Reordering lifecycle groups.
- Redesigning unrelated plugin workspaces.

# Acceptance criteria

- Every valid proposal inspection includes its canonical `created_at` value.
- Proposal rows and selected proposal details display a readable creation date
  and time in the user's local timezone.
- Items in each lifecycle group are ordered from newest to oldest.
- Invalid timestamps degrade to the original value instead of breaking render.
- Desktop tests, plugin typecheck/tests/build/artifact tests, installed-artifact
  comparison, and diff checks pass.

# Validation

```bash
uv run pytest -q tests/desktop/test_proposals.py
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
cmp packages/obsidian-plugin/build/main.js /absolute/vault/.obsidian/plugins/lifeos/main.js
git diff --check
```

# Relevant decisions

- DD-031: Proposal lifecycle metadata remains canonical Markdown.
- DD-036: Obsidian is the primary interface and Python owns proposal semantics.
- DD-037: The plugin remains a thin client over the desktop bridge.

# Implementation record

- Added canonical `created_at` to the desktop proposal inspection returned by
  `proposal.list` and `proposal.inspect`.
- Added a resilient local date/time formatter for the Obsidian client; malformed
  values remain visible as their original strings.
- Rendered creation time on proposal-list rows and in selected-proposal metadata.
- Sorted proposals newest-first within each lifecycle group with stable title
  and proposal-ID tie-breakers.
- Rebuilt and installed the verified JavaScript, stylesheet, and manifest in the
  configured LifeOS vault.

# Validation record

- Focused desktop proposal tests: 3 passed.
- Python Ruff and strict mypy checks: passed.
- Obsidian plugin typecheck: passed.
- Obsidian plugin tests: 50 passed.
- Production plugin build: passed.
- Artifact tests: 2 passed.
- Installed plugin artifacts match the verified build byte-for-byte.
- `git diff --check`: passed.
