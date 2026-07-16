---
id: LIFEOS-1104
title: Diagnose repeated avoidance and stalled task shapes
status: completed
phase: 11
depends_on:
  - LIFEOS-1101
  - LIFEOS-1007
risk: high
---

# Goal

Turn repeated skips, deferrals, partial completions, and unaccounted outcomes into
careful diagnostic questions and reversible suggestions rather than endless
rescheduling or blame.

# Scope

- Add deterministic detection for repeated avoidance and stalled work.
- Distinguish patterns such as:
  - underspecified next action
  - task larger than available windows
  - unresolved blocker
  - recurring estimate error
  - mode or context mismatch
  - low motivation despite adequate energy
  - plan without a meaningful next action
  - stale or questionable goal alignment
  - routine prompt that is repeatedly dismissed
- Require configurable repetition, recency, and evidence thresholds.
- Produce typed diagnoses containing evidence, competing explanations,
  confidence, suggested questions, and safe actions.
- Integrate with the attention queue without duplicating attention-item state.
- Support actions such as clarify, decompose, reduce duration, change mode, add a
  blocker, pause, review the goal, dismiss, or ask later.
- Route consequential changes through proposals and the existing proposal UI.
- Permit an optional agent to draft a decomposition only after the user requests
  it.

# Out of scope

- Psychological diagnosis or labels.
- Automatically pausing plans or rewriting goals.
- Treating one missed task as a behavioral pattern.
- Scoring discipline, willpower, or productivity.
- LLM calls for ordinary threshold detection.

# Required invariants

- Silence remains unaccounted, not skipped.
- Diagnoses are hypotheses, never facts about the user's character.
- Every diagnosis cites concrete canonical outcomes and dates.
- Competing explanations and missing evidence remain visible.
- Dismissal and correction influence future surfacing deterministically.
- Consequential suggestions require explicit proposal approval.
- The system can recommend reducing or removing tracking itself.

# Required tests

- One skip versus repeated skips across the configured boundary.
- Repeated partial completion and repeated unaccounted outcomes.
- Mixed outcomes that should suppress diagnosis.
- Underspecified, blocked, oversized, and estimate-error examples.
- Competing explanations and insufficient evidence.
- Dismiss, snooze, correct, and reappear-after-new-evidence behavior.
- Task renamed, completed, archived, or plan paused after diagnosis.
- Stable diagnosis IDs and no duplicate attention cards.
- Language checks preventing punitive or clinical wording.

# Acceptance criteria

- Repeated avoidance produces a useful reconciliation or proposal path.
- No diagnosis silently changes canonical work.
- The result is explainable enough for the user to disagree productively.
- Full tests, Ruff, mypy, plugin tests, and diff checks pass.

# Validation commands

```bash
pytest tests/planning_feedback/test_avoidance.py tests/attention tests/planning tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-021: Adaptive planning, not conventional task management
- DD-022: Goals are directions
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
