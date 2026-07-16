---
id: LIFEOS-905
title: Deterministic bounded workload optimization
status: completed
phase: hardening
depends_on: []
risk: medium
---

# Goal

Replace locally greedy study and daily-menu selection with a documented,
deterministic bounded optimizer that balances urgency, capacity use, and
variety without hiding trade-offs.

# Discovered issue

The current study and planning selectors rank candidates and greedily accept the
next fitting item. This can leave usable capacity empty even when a better
combination exists. Plan-diversity rules may also defer high-ranked actions
without evaluating the complete menu. The intended priority among urgency,
capacity utilization, diversity, energy fit, and motivation fit is not encoded
as an explicit optimization contract.

# Scope

- Define ordered optimization objectives separately for study and planning.
- Preserve hard constraints such as time budget, blockers, due eligibility, and
  allowed energy values.
- Model soft preferences such as urgency, overdue duration, energy fit,
  motivation fit, topic or plan diversity, and mode.
- Implement a deterministic bounded solver, such as dynamic programming or
  branch-and-bound with explicit candidate and capacity limits.
- Define stable tie-breaking independent of input traversal order.
- Return diagnostics showing selected score, rejected candidates, binding
  constraints, unused capacity, and diversity trade-offs.
- Keep flashcards grouped into workload sessions rather than one task per card.
- Keep daily planning advisory rather than imperative.
- Add a documented fallback when the candidate set exceeds the exact-solver
  bound.

# Out of scope

- Machine-learned ranking.
- Automatic rescheduling without user approval.
- Treating diet, exercise, or hobbies only as productivity variables.
- Optimizing across multiple days in the first implementation.
- Changing canonical goal, plan, or flashcard formats.

# Required tests

- Greedy counterexample where a combination fills more useful capacity.
- High-urgency item remains selected when that is the primary objective.
- Diversity preference does not violate hard urgency or blocker constraints.
- Stable result under shuffled candidate input.
- Exact boundary at zero, one, and maximum supported capacity.
- Oversized candidate set uses the documented deterministic fallback.
- Diagnostics explain unused time and rejected high-ranked items.
- Energy and motivation remain distinct scoring dimensions.
- Study grouping and planning menu semantics remain intact.

# Acceptance criteria

- Optimization objectives and their order are documented in code and user-facing
  diagnostics.
- Selection is deterministic and independent of filesystem traversal order.
- Known greedy counterexamples produce the intended superior menu or session.
- Runtime is bounded for realistic vault sizes.
- Existing simple scenarios remain unchanged unless the new policy explicitly
  improves them.

# Validation commands

```bash
pytest tests/study tests/planning tests/cli/test_study_cli.py tests/cli/test_plan_cli.py
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-023: Tasks stay with plans
- DD-024: Flashcards are workload sessions
- DD-025: Energy and motivation are distinct
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-027: Skipped tasks trigger diagnosis
