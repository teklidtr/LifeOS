---
id: LIFEOS-1506
title: Build Obsidian experiment workspace
status: completed
phase: 15
depends_on:
  - LIFEOS-1505
risk: high
---

# Goal

Build the graphical experiment workspace, history browser, contextual entry points, accessible state model, and keyboard-first controller.

# Implemented

- Added typed experiment artifact, protocol, observation, analysis, safety, history, comparison, and proposal contracts for the plugin.
- Added a UI-first workspace controller for experiment creation, design guidance, safety review, lifecycle transitions, observations, due windows, protocol amendments, deterministic analysis, conclusions, cloning, history, comparisons, and proposal review.
- Added explicit loading, empty, unsafe, stale, malformed, unsupported-schema, missing-index, rebuild, provider, insufficient-evidence, conflicting-edit, proposal, and migration states.
- Added ribbon, command-palette, active-note, history, goal, plan, task, capture, daily-review, weekly-review, and knowledge-conversation entry-point routing.
- Added keyboard actions, focus targets, accessible labels, and screen-reader status announcements.
- Kept all business-rule mutations on strict bridge methods and exposed no direct proposal-application action.

# Required invariants verified

- Canonical Markdown remains the source of truth and can be opened directly.
- Explicit missing observation states remain distinct from zero.
- Unsafe experiments surface a blocked state before activation.
- Protocol changes after activation use dated amendments.
- Analysis remains deterministic and descriptive.
- Follow-up changes remain proposal-gated.

# Validation

- `cd packages/obsidian-plugin && npm run typecheck`: passed.
- `cd packages/obsidian-plugin && npm test`: 38 passed.
- `cd packages/obsidian-plugin && npm run build`: passed.
- `git diff --check`: passed.
