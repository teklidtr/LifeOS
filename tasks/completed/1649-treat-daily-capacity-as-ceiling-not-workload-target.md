---
id: LIFEOS-1649
title: Treat daily planning capacity as a ceiling, not a workload target
status: completed
phase: hardening
depends_on:
  - LIFEOS-905
risk: medium
---

# Goal

Align the deterministic daily-menu optimizer with the LifeOS philosophy that available time is a feasibility boundary, not an implicit quota to fill.

The current baseline planner explicitly rewards `capacity used` and `item count`, and its energy/motivation fit totals also grow mechanically when more equally fitting actions are added. That can make a larger menu score better merely because more work fits inside the declared day. LifeOS should instead treat `available_minutes` as a hard upper bound while recommending a small, realistic menu for explicit reasons such as urgency, fit, blockers, and useful plan diversity.

# Scope

- Add a durable design decision stating that daily `available_minutes` is a hard ceiling, not a workload target, productivity quota, or expectation that free capacity should be consumed.
- Update the baseline daily-menu optimization contract so a menu is not preferred merely because it:
  - uses more available minutes;
  - contains more items; or
  - accumulates larger energy/motivation fit totals solely by adding more equally fitting actions.
- Remove `capacity used` and `item count` as positive optimization objectives.
- Make energy and motivation fit aggregation size-neutral so adding another otherwise equivalent action does not mechanically improve fit merely because another term was summed.
- Preserve additive urgency where multiple genuinely due/overdue actions provide additional explicit scheduling evidence.
- Preserve hard constraints for available time, blockers, action status, required energy, and optional mode filtering.
- Preserve energy and motivation as distinct dimensions.
- Preserve plan variety only as a bounded soft preference that cannot turn spare time into an obligation to add more work.
- Define deterministic tie-breaking for otherwise equivalent menus without preferring greater workload. Prefer the lower-workload equivalent before the existing stable-ID tie break unless a higher-priority documented objective distinguishes the menus.
- Keep both the exact solver and deterministic bounded fallback aligned with the same ceiling-not-quota semantics.
- Keep diagnostics inspectable. Remaining capacity may still be reported, but it must not be framed or scored as a failure to use time.
- Preserve existing public result/schema fields where practical; do not introduce compatibility churn merely to rename `unused_minutes` if its meaning can be documented as neutral remaining capacity.
- Add regression tests that demonstrate the philosophical boundary rather than only checking implementation details.

# Out of scope

- Calendar scheduling or multi-day optimization.
- Automatic rescheduling or plan mutation.
- Machine-learned ranking.
- A universal productivity, discipline, utilization, or personal-worth score.
- Treating exercise, diet, hobbies, rest, or unallocated time as productivity deficits.
- Introducing a default target workload, target utilization percentage, or reserve quota.
- A new user-facing `target_load_minutes` / `reserve_minutes` feature. If explicit workload targets are useful later, they should be separate opt-in work and must remain distinct from `available_minutes`.
- Redesigning adaptive-feedback evidence or goal-to-plan decomposition beyond changes required to keep the baseline planner contract consistent.

# Required tests

- A high-priority action plus several equally fitting, non-urgent optional actions does not expand into a fuller menu solely because spare capacity exists.
- Increasing `available_minutes` alone does not make an otherwise equivalent larger workload score better when no higher-priority scheduling evidence changes.
- Two menus with equal urgency, fit, and bounded diversity prefer the lower-workload equivalent before stable-ID tie-breaking.
- Multiple genuinely due/overdue actions may still outrank a smaller menu because additive urgency is explicit evidence rather than utilization pressure.
- Energy and motivation remain distinct and their fit aggregation does not mechanically increase with menu size.
- Blockers, required energy, status, mode filtering, and the hard time ceiling remain unchanged.
- Exact and fallback solvers follow the same ceiling-not-quota policy.
- Results remain deterministic under shuffled candidate input.
- Diagnostics continue to expose selected and remaining minutes without treating remaining capacity as a negative score.

# Acceptance criteria

- `available_minutes` constrains feasibility but is not a positive optimization target.
- No optimization objective rewards raw selected duration or raw item count.
- Energy/motivation fit scoring is normalized or otherwise defined so additional equally fitting items do not gain score merely from count.
- Equivalent menus do not prefer the larger workload solely because it consumes more time.
- Genuine urgency, blocker resolution, energy/motivation fit, and bounded plan diversity can still explain why an action is recommended.
- The daily menu remains advisory: spare capacity is allowed and requires no explanation as a failure.
- A new accepted design decision records this contract so future planner/adaptive work cannot silently reintroduce utilization maximization.
- User-facing adaptive-planning documentation explains that declared capacity is a ceiling and that LifeOS does not try to fill every available minute.
- Relevant planning tests, repository validation, and documentation checks pass.

# Documentation impact

Status: required

- `docs/design-decisions.md`: add the durable capacity-ceiling / no implicit utilization-target decision.
- `docs/architecture.md`: align the adaptive-planning contract and optimizer description with ceiling-not-quota semantics.
- `docs/user-manual/08-adaptive-planning.md`: explain that available time is a maximum feasible budget, not a target LifeOS tries to fill, and that remaining capacity is neutral.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/planning
uv run pytest --import-mode=importlib -q tests/planning_feedback tests/integration/test_adaptive_feedback_release.py
uv run python scripts/validate_manual_links.py
uv run ruff check src tests
uv run mypy src
uv run pytest --import-mode=importlib -q
```

# Relevant decisions

- DD-021: Adaptive planning, not conventional task management.
- DD-022: Goals are directions.
- DD-023: Tasks stay with plans.
- DD-025: Energy and motivation are distinct.
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs.
- DD-027: Skipped tasks trigger diagnosis rather than endless rescheduling.
- DD-040: Adaptive planning is optional, bounded, and baseline-visible.
- DD-044: Historical replay forbids universal scores.
- LIFEOS-905: Deterministic bounded workload optimization introduced the current ordered objective contract that this task refines.
