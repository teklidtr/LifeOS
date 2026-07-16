---
id: LIFEOS-1103
title: Model task fit for energy, motivation, mode, and context
status: completed
phase: 11
depends_on:
  - LIFEOS-1101
risk: high
---

# Goal

Estimate how well different task shapes fit the user's recorded capacity and
pull while preserving the distinction between energy and motivation.

# Scope

- Derive cautious task-fit summaries from explicit execution outcomes.
- Analyze dimensions such as:
  - required versus recorded energy
  - required versus recorded motivation
  - mode
  - duration band
  - time window when explicitly known
  - blocker state
  - completion, partial, skip, defer, and cancellation outcomes
- Use deterministic, bounded statistics with minimum sample thresholds.
- Report sample counts, missingness, freshness, effect direction, uncertainty,
  contradictions, and confidence labels.
- Support hierarchical fallback from specific task shape to mode-level and global
  evidence.
- Treat journal health metrics and personal observations as contextual evidence,
  not causal inputs.
- Expose typed read-only summaries for the planner and review UI.
- Add user controls to disable individual dimensions from adaptive use.

# Out of scope

- Medical, psychological, or causal claims.
- Automatic schedule optimization across calendar events.
- Inferring mood or motivation from writing style.
- Editing task requirements in canonical plans.
- Black-box prediction scores.

# Required invariants

- Energy and motivation are never collapsed into one productivity number.
- Missing observations do not count as negative outcomes.
- Associations are labeled tentative and noncausal.
- Sparse evidence cannot materially change recommendations.
- Every fit adjustment is capped, inspectable, and reversible.
- Hobbies, exercise, and rest are not penalized as unproductive behavior.

# Required tests

- Distinct energy and motivation effects.
- High energy with low motivation and the inverse case.
- Missing context fields and uneven missingness.
- Conflicting evidence across plans or modes.
- Minimum sample, freshness, and fallback boundaries.
- Time-window and DST cases when time evidence exists.
- Disabled dimensions and complete adaptive reset.
- Determinism under shuffled observations.
- No causal or diagnostic wording in returned explanations.

# Acceptance criteria

- The planner can ask for a typed, cautious fit adjustment for a candidate.
- The user can see which dimensions contributed and which were ignored.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/planning_feedback/test_capacity_fit.py tests/observation tests/planning tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-027: Skipped tasks trigger diagnosis
