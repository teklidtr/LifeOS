---
id: LIFEOS-1612
title: Package a loadable Obsidian desktop plugin
status: completed
phase: 16
depends_on:
  - LIFEOS-1003
  - LIFEOS-1012
risk: medium
---

# Goal

Replace the test-only TypeScript output with a real Obsidian desktop entry point and a
reproducible, self-contained plugin bundle.

# Scope

- Add an Obsidian `Plugin` adapter around the existing thin LifeOS controller.
- Add settings, workspace-view, vault-path, and STDIO bridge adapters.
- Bundle the plugin into one CommonJS `build/main.js` with Obsidian externalized.
- Declare and lock the TypeScript, Obsidian, Node, and bundler development dependencies.
- Add a release-artifact smoke test and correct installation documentation.

# Out of scope

- Reimplementing Python business rules in TypeScript.
- Completing every controller-specific visual workspace.
- Public Obsidian community-plugin publication.
- Changing canonical vault content or the Python bridge protocol.

# Acceptance criteria

- `build/main.js` default-exports an Obsidian plugin class and has no missing relative modules.
- The plugin can launch the configured Python module over JSON-RPC STDIO.
- Settings persist the configuration path, Python executable, actor ID, startup behavior,
  and diagnostic level.
- Unit tests, type-checking, production build, artifact smoke test, and diff checks pass.

# Validation commands

```bash
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
npm --prefix packages/obsidian-plugin run test:artifact
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-037: The default desktop transport is a vault-scoped STDIO child process
- DD-038: Direct UI writes use optimistic concurrency and idempotency
