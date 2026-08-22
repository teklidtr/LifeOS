---
id: LIFEOS-1618
title: Fix proposal workspace text overflow
status: completed
phase: 16
depends_on:
  - LIFEOS-1614
risk: low
---

# Goal

Keep long proposal titles, paths, IDs, and digests inside their Obsidian
proposal-workspace columns at normal and narrow pane widths.

# Scope

- Allow both proposal grid columns and their children to shrink correctly.
- Wrap long proposal labels, headings, metadata, paths, and code-like values.
- Use proposal-pane container width for the single-column responsive layout.
- Add an artifact-level CSS regression test.

# Out of scope

- Changing proposal data or lifecycle behavior.
- Redesigning unrelated Obsidian views.
- Truncating information that the reviewer must inspect.

# Acceptance criteria

- Long Turkish titles and vault paths do not paint across column boundaries.
- Long SHA-256 digests remain visible and wrap within the detail pane.
- Narrow proposal panes switch to one column independently of window width.
- Plugin typecheck, tests, build, artifact test, and diff checks pass.

# Validation commands

```bash
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
git diff --check
```

# Relevant design decisions

- DD-036: Obsidian is the primary interface
- DD-037: The plugin remains a thin desktop client

# Implementation record

- Added shrink-safe proposal grid tracks and children.
- Added wrapping for proposal buttons, headings, metadata, paths, code, and
  digest-like values without truncating review information.
- Added a named inline-size container so narrow Obsidian panes collapse to one
  column independently of the application window width.
- Copied the verified built stylesheet to the installed vault plugin.

# Validation record

- TypeScript typecheck passed.
- All 49 plugin tests passed.
- Production plugin build passed.
- Both artifact tests passed, including the new CSS regression assertions.
- Installed stylesheet exactly matches the built artifact.
- `git diff --check` passed.
