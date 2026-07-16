---
id: LIFEOS-1209
title: Build the Obsidian goal-to-plan copilot workspace
status: completed
phase: 12
depends_on:
  - LIFEOS-1203
  - LIFEOS-1206
  - LIFEOS-1207
  - LIFEOS-1208
risk: high
---

# Goal

Provide the complete goal-to-plan workflow inside Obsidian so ordinary use does
not require commands or raw JSON.

# Scope

- Add entry points from goal notes, Quick Capture, goal review, and the LifeOS
  command palette.
- Build a resumable workspace for context preview, clarification questions,
  plan-option comparison, milestone and action editing, capacity conflicts,
  explanations, and proposal handoff.
- Support keyboard-only operation and clear focus management.
- Add explicit controls for include, exclude, redact, regenerate, edit, compare,
  save draft, resume, park, abandon, and create proposal.
- Display stale source, invalid output, denied scope, missing model, bridge
  restart, recovery required, and incompatible protocol states distinctly.
- Keep transient conversation and form state disposable while preserving durable
  session records through Python services.
- Add command and view tests using deterministic fixtures.

# Out of scope

- Reimplementing planning or proposal rules in TypeScript.
- Mobile parity.
- A general AI chat sidebar.
- Calendar scheduling.

# Required invariants

- Obsidian is the primary interaction surface.
- Python remains the sole business-rule and validation engine.
- The user can inspect model-bound context before sending it.
- No button bypasses proposal approval or stale-write protection.
- Closing or restarting Obsidian does not corrupt a planning session.
- Uninstalling the plugin leaves readable Markdown and proposal files.

# Required tests

- Start from goal note and Quick Capture.
- Deterministic-only and model-assisted flows.
- Save, close, resume, abandon, and park.
- Compare options and edit individual fields.
- Context include, exclude, preview, and redaction.
- Missing bridge, model, permission, and protocol compatibility.
- Stale note during review and stale proposal during application.
- Keyboard-only critical path and accessible labels.
- Plugin restart and bridge restart during a session.

# Acceptance criteria

- A new user can complete a goal-to-plan flow without opening a terminal.
- The UI exposes safety boundaries instead of hiding them behind generic errors.
- Python and TypeScript suites, lint, type checks, and build pass.

# Validation commands

```bash
pytest tests/bridge tests/desktop tests/planning tests/proposals tests/e2e -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin run build
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-007: Native Obsidian references first
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-037: The default desktop transport is a vault-scoped STDIO child process
- DD-038: Direct UI writes use optimistic concurrency and idempotency
