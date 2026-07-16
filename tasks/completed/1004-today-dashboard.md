---
id: LIFEOS-1004
title: Build the Obsidian Today dashboard
status: backlog
phase: 10
depends_on:
  - LIFEOS-1001
  - LIFEOS-1003
risk: medium
---

# Goal

Provide a single Obsidian home view that assembles today's state and actionable
choices from canonical LifeOS data without requiring the user to run commands or
inspect YAML.

# Scope

- Add a typed Python read model for the Today view.
- Compose:
  - current journal/check-in state
  - available-time and capacity inputs
  - adaptive daily menu
  - due study workload summary
  - active experiments or habits when present
  - inbox count
  - pending proposal count
  - attention items
  - serious system diagnostics
- Build an Obsidian dockable view with explicit refresh and automatic
  invalidation after relevant vault changes.
- Show why each proposed action was selected and why deferred candidates did not
  fit.
- Allow the user to adjust time, energy, motivation, and mode before refreshing
  the proposed menu.
- Link every card to its canonical Markdown source.
- Preserve scroll and local UI state across harmless refreshes.
- Distinguish missing data from zero, false, complete, or intentionally disabled.

# Out of scope

- Writing check-ins or task outcomes; later tasks add those actions.
- AI-generated recommendations.
- A standalone web dashboard.
- Calendar integration.
- Background notifications.

# Required invariants

- The dashboard is a generated read model, not canonical state.
- Opening or refreshing the dashboard is read-only.
- Planner and study selection remain deterministic Python services.
- Stale, blocked, corrupt, and unavailable components remain distinguishable.
- A failure in one card does not erase unrelated healthy sections.

# Required tests

- Empty vault and partially configured vault.
- Missing journal with valid plans and study data.
- Planner failure while other dashboard sections still render.
- Stable ordering and identical results after shuffled filesystem iteration.
- Relevant note edit invalidates the correct sections.
- Unrelated note edit does not trigger unnecessary recomputation.
- Canonical source links open the expected note and heading.
- Text scaling, keyboard navigation, and screen-reader labels.

# Acceptance criteria

- The user can understand today's actionable state from one Obsidian view.
- No terminal command is required to generate or refresh the view.
- Every displayed fact is traceable to canonical or typed derived evidence.
- Python and plugin tests pass.

# Validation commands

```bash
pytest tests/daily tests/planning tests/study tests/status -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-008: Description is the lightweight summary field
- DD-021: Adaptive planning, not conventional task management
- DD-024: Flashcards are workload sessions
- DD-025: Energy and motivation are distinct
