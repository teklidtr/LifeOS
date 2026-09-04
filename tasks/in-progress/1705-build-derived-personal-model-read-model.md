---
id: LIFEOS-1705
title: Build the derived Personal Model read model
status: in-progress
phase: 17
depends_on:
  - LIFEOS-1701
  - LIFEOS-1702
  - LIFEOS-1704
risk: medium
---

# Goal

Provide one inspectable view of tracked working hypotheses without creating another canonical semantic authority.

# Scope

- Build a rebuildable Personal Model index under `.lifeos/`.
- Index canonical patterns by stable ID, status, confidence, review reasons, evidence freshness, origin, and review due state.
- Produce a typed read model for active hypotheses, seeds, needs-review items, archived items, and evidence-health diagnostics.
- Preserve individual pattern IDs and canonical source links.
- Rebuild entirely from canonical Markdown.

# Out of scope

- Writing `profile/personal-model.md`.
- Generating a personality narrative.
- Hidden universal scores.
- Modifying patterns.
- Planner ranking changes.

# Required invariants

- Deleting `.lifeos/` Personal Model state loses no canonical knowledge.
- Every read-model item traces to canonical Markdown.
- Ordering is deterministic.
- Malformed patterns surface diagnostics rather than appearing healthy.

# Acceptance criteria

- Personal Model state is fully rebuildable.
- Empty, mixed-status, malformed, changed-evidence, duplicate-ID, and delete/rebuild cases are covered.
- No aggregate narrative becomes authoritative.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document the derived-state contract.
- `docs/architecture.md`: add the Personal Model read-model layer.
- `docs/user-manual/`: explain canonical patterns versus the derived model.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-001
- DD-008
- DD-013
- DD-033
- DD-039
- DD-061
