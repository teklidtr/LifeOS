---
id: LIFEOS-1009
title: Build guided daily and weekly review workflows
status: completed
phase: 10
depends_on:
  - LIFEOS-1005
  - LIFEOS-1006
  - LIFEOS-1007
  - LIFEOS-1008
risk: high
---

# Goal

Turn the manual's morning, evening, and weekly review routines into guided
Obsidian workflows that reconcile facts, invite reflection, and write a
human-readable canonical review note.

# Scope

- Add guided flows for:
  - morning orientation
  - evening reconciliation
  - weekly review
- Build deterministic review inputs from inbox items, active plans, unfinished
  actions, repeated avoidance, study backlog, proposal state, personal evidence,
  graph/export health, and attention items.
- Create review notes under `reviews/` with:
  - a managed deterministic facts block
  - a human-owned reflection section
  - stable review identity and date range
- Allow progress to be saved and resumed.
- Link every review item to its canonical source.
- Add focused actions to clarify, complete, defer, archive, or open an item.
- Route consequential AI suggestions through proposals.
- Avoid demanding that every optional section be completed.

# Out of scope

- Automatic interpretation of personal patterns.
- Automatic deletion or archival.
- Calendar scheduling.
- Gamified completion scores.
- Background notification delivery.

# Required invariants

- Generated review facts are rebuildable and visibly separated from reflection.
- Human reflection is never overwritten by regeneration.
- Completing one review action cannot silently resolve unrelated items.
- Review progress and final canonical output have explicit state boundaries.
- A failed subsystem does not prevent reviewing healthy sections.
- The workflow remains useful with sparse data.

# Required tests

- First-ever review with an almost empty vault.
- Resume after plugin restart.
- Rebuild managed facts while preserving human reflection.
- Weekly boundary, timezone, and year-transition cases.
- Repeatedly skipped task appears with evidence rather than accusation.
- Pending proposal and stale export sections link correctly.
- Partial completion and intentional section skipping.
- Concurrent manual edit of the review note causes a safe conflict.

# Acceptance criteria

- The user can complete daily and weekly reviews without terminal commands.
- Review notes are readable and useful without the plugin.
- Managed and human-owned sections are protected correctly.
- Full tests, Ruff, mypy, and plugin checks pass.

# Validation commands

```bash
pytest tests/reviews tests/daily tests/attention tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-009: Managed blocks
- DD-012: Preservation checks are scripted
- DD-016: Adversarial review is selective
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
