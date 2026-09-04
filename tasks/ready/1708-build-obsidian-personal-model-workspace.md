---
id: LIFEOS-1708
title: Build the Obsidian Personal Model workspace
status: ready
phase: 17
depends_on:
  - LIFEOS-1703
  - LIFEOS-1704
  - LIFEOS-1705
  - LIFEOS-1706
risk: medium
---

# Goal

Give the user an Obsidian-native surface for inspecting and maintaining working hypotheses without editing YAML or using terminal commands.

# Scope

- Add a dockable Personal Model workspace with Active, Needs review, Seeds, and Archived views.
- Show hypothesis statement, confidence, evidence health, review reasons, and freshness.
- Open supporting and contesting canonical sources.
- Show evidence changes since the last review.
- Support proposal-backed Track, Adopt, Revise, Contest, and Archive actions.
- Link to relevant reviews and experiments.
- Provide empty, degraded, stale, and blocked states.
- Preserve keyboard navigation and accessibility.

# Out of scope

- Personality dashboards.
- Gamification or scores.
- Automatic suggestions on every startup.
- Direct Markdown mutation in TypeScript.

# Required invariants

- Python remains the sole business-rule engine.
- UI refresh is read-only.
- Consequential actions produce proposals.
- Evidence is visible before adoption or revision.
- Missing runtime state degrades to rebuild/recovery rather than data loss.

# Acceptance criteria

- A user can understand why a pattern deserves attention and inspect its evidence.
- Normal pattern review requires no terminal command.
- No pattern can be silently changed from the plugin.
- Tests cover empty/mixed states, evidence navigation, proposal preview, stale target, runtime rebuild, keyboard workflow, screen-reader labels, and text scaling.

# Documentation impact

Status: required

- `docs/user-manual/06-obsidian-desktop.md`: document the Personal Model workspace.
- `docs/user-manual/`: add the Phase 17 user workflow.
- `docs/personal-model-architecture.md`: document the bridge/UI boundary.

# Validation commands

- `pytest -q`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-036
- DD-037
- DD-038
- DD-080
- Phase 17 Personal Model architecture
