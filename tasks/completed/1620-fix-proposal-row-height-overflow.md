---
id: LIFEOS-1620
title: Fix wrapped proposal row height in Obsidian
status: completed
phase: 16
depends_on:
  - LIFEOS-1618
risk: low
---

# Goal

Make proposal-list buttons grow vertically with wrapped titles and IDs so their
content cannot overlap lifecycle group headings or neighboring rows.

# Scope

- Override Obsidian's fixed button height for proposal-list rows.
- Preserve the existing horizontal wrapping and responsive proposal layout.
- Add artifact assertions for content-driven height and usable minimum height.
- Rebuild and copy the verified plugin artifacts into the configured vault.

# Out of scope

- Changing proposal lifecycle data or bridge behavior.
- Truncating proposal titles or IDs.
- Redesigning other plugin workspaces.

# Acceptance criteria

- A multi-line title and proposal ID remain inside the selected-row background.
- The next lifecycle heading begins after the complete proposal row.
- Short rows retain a usable Obsidian control height.
- Plugin typecheck, tests, build, artifact tests, installed-artifact comparison,
  and diff checks pass.

# Validation

```bash
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
cmp packages/obsidian-plugin/build/styles.css /absolute/vault/.obsidian/plugins/lifeos/styles.css
git diff --check
```

# Relevant decisions

- DD-036: Obsidian is the primary interface.
- DD-037: The plugin remains a thin desktop client.

# Implementation record

- Increased selector specificity to target proposal buttons explicitly.
- Overrode Obsidian's fixed input height with content-driven `height: auto` while
  retaining `--input-height` as the minimum control height.
- Added vertical padding and centered short-row content without truncating long
  titles or IDs.
- Rebuilt the plugin and copied the verified stylesheet into the configured
  LifeOS vault.

# Validation record

- TypeScript typecheck passed.
- All 49 plugin tests passed.
- Production plugin build passed.
- Both artifact tests passed with new row-height assertions.
- Installed stylesheet exactly matches the built artifact.
- `git diff --check` passed.
- Obsidian was cleanly restarted and visually verified: wrapped titles and IDs
  remain within their row backgrounds and lifecycle headings no longer overlap.
