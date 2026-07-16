---
id: LIFEOS-1207
title: Add plan-option explanations, provenance, and comparison
status: backlog
phase: 12
depends_on:
  - LIFEOS-1204
  - LIFEOS-1205
  - LIFEOS-1206
risk: medium
---

# Goal

Make every suggested plan, milestone, action, and conflict understandable enough
for the user to edit or reject it confidently.

# Scope

- Add typed explanations for why each option exists, what evidence supports it,
  which assumptions it uses, and what tradeoffs distinguish it.
- Trace generated fields to user answers, canonical note references,
  deterministic planning facts, adaptive evidence, or agent interpretation.
- Add side-by-side comparison for scope, pace, uncertainty, capacity fit, risks,
  reversible first steps, and unresolved questions.
- Add counterfactual explanations for common edits such as less available time,
  lower desired pace, removed deadline, or excluded context.
- Add contradiction and omission summaries.
- Expose explanation data through facade and bridge contracts.

# Out of scope

- Revealing hidden chain of thought.
- Assigning one universal score to plan options.
- Recommending a winner without user-visible criteria.
- Applying edits.

# Required invariants

- Explanations cite inspectable inputs rather than model authority.
- User-authored facts and agent assumptions are visually distinct.
- Missing evidence remains visible.
- Comparison dimensions are explicit and independently inspectable.
- Counterfactuals are recalculated through bounded services, not improvised prose.

# Required tests

- Fully supported, assumption-heavy, contradictory, and sparse options.
- Deterministic and agent-generated fields in one option.
- Missing, stale, deleted, and excluded source references.
- Baseline versus adaptive capacity explanations.
- Counterfactual recomputation.
- Stable ordering and serialization.
- Invalid explanation references rejected by validation.

# Acceptance criteria

- A user can answer "why this plan?" and "why this task?" without trusting an
  opaque model judgment.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/planning tests/context tests/facade tests/bridge tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-005: Status and confidence
- DD-015: Knowledge gaps use evidence signals
- DD-022: Goals are directions
