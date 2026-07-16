---
id: LIFEOS-1107
title: Add adaptive-feedback controls to the Obsidian dashboard
status: completed
phase: 11
depends_on:
  - LIFEOS-1004
  - LIFEOS-1006
  - LIFEOS-1105
  - LIFEOS-1106
risk: high
---

# Goal

Let the user inspect, correct, accept, dismiss, disable, and reset adaptive
feedback entirely from Obsidian without editing YAML or using terminal commands.

# Scope

- Add Today-dashboard surfaces for adaptive recommendations and confidence.
- Add **Why this?**, **Why not?**, baseline comparison, and expanded evidence
  panels.
- Add outcome correction and missing-data clarification flows.
- Add controls to:
  - keep the declared estimate
  - use the calibrated estimate for this session only
  - disable one feedback dimension
  - dismiss a diagnosis
  - correct a mistaken outcome
  - exclude a record from adaptation while preserving history
  - switch between off, shadow, and active modes
  - reset all derived feedback
- Show what a reset removes before confirmation.
- Add accessible keyboard navigation, screen-reader labels, and non-color status
  indicators.
- Keep all mutations behind typed Python services with stale-write and
  idempotency protection.
- Add optimistic UI only where rollback behavior is explicit.

# Out of scope

- Reimplementing calibration or planner logic in TypeScript.
- Silent acceptance of learned estimates.
- Editing journal prose.
- Mobile parity.
- Automatic agent conversations.

# Required invariants

- The dashboard is a view and controller, not a second source of truth.
- Every correction reads the current canonical record before writing.
- Dismissal is not interpreted as agreement or failure.
- Reset is reversible with respect to canonical history and cannot delete it.
- Adaptive mode is always visible.
- The baseline menu remains one click away.
- Plugin failure leaves the vault valid and readable.

# Required tests

- Off, shadow, and active mode presentation.
- Baseline and adaptive menu comparison.
- Correct outcome, exclude record, dismiss diagnosis, disable signal, and reset.
- Stale canonical record during a correction.
- Bridge restart and retry with idempotency key.
- Keyboard-only and screen-reader critical paths.
- No duplicate writes after UI retries.
- Plugin disable/re-enable preserving canonical history and preferences.

# Acceptance criteria

- Ordinary feedback management requires no CLI or manual YAML editing.
- The user can disagree with LifeOS and see the effect immediately.
- Python and TypeScript suites, lint, type checks, and builds pass.

# Validation commands

```bash
pytest tests/planning_feedback tests/daily tests/bridge tests/integration -q
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-007: Native Obsidian references first
- DD-011: Read before write
- DD-021: Adaptive planning, not conventional task management
- DD-027: Skipped tasks trigger diagnosis
