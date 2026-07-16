---
id: LIFEOS-1204
title: Generate structured medium-term plan options
status: completed
phase: 12
depends_on:
  - LIFEOS-1201
  - LIFEOS-1202
  - LIFEOS-1203
  - LIFEOS-114
risk: high
---

# Goal

Generate a small set of genuinely different, structured plan options from an
explicitly ready goal and its approved context pack.

# Scope

- Generate zero to three plan options with distinct strategy, scope, pace, or
  uncertainty posture rather than cosmetic rewrites.
- Require each option to include desired outcome, boundaries, assumptions,
  success evidence, major risks, review date, coarse milestones, likely resource
  demands, and reasons it may not fit.
- Include a no-plan or experiment-first option when evidence is weak or the goal
  is exploratory.
- Validate all output through typed schemas and deterministic checks.
- Detect duplication with existing active or archived plans.
- Preserve source references and distinguish user facts from agent assumptions.
- Support provider-neutral adapters and deterministic fixtures for tests.

# Out of scope

- Creating detailed tasks for distant milestones.
- Selecting the winning option automatically.
- Applying a plan to the vault.
- Daily scheduling.

# Required invariants

- The copilot may return no viable plan option.
- Every assumption is visible and editable.
- Options do not invent deadlines, budgets, skills, or commitments.
- Existing plans are considered before creating a new one.
- Model output cannot directly produce canonical writes.
- Strategy differences are explainable and testable.

# Required tests

- One strong option, several meaningful alternatives, and no viable option.
- Experiment-first and link-existing-plan outcomes.
- Duplicate and near-duplicate plan detection.
- Missing context, contradictions, and stale context packs.
- Hallucinated identifiers, dates, references, and constraints.
- Invalid schema, excessive output, and provider failure.
- Deterministic fixture replay across adapter versions.

# Acceptance criteria

- The user can compare options by tradeoff rather than prose volume.
- Generated options are safe inputs to rolling-wave decomposition.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/planning tests/ai tests/context tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-011: Read before write
- DD-022: Goals are directions
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
