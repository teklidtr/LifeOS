---
id: LIFEOS-1201
title: Define goal, plan, milestone, and planning-session contracts
status: completed
phase: 12
depends_on:
  - LIFEOS-1200
risk: high
---

# Goal

Create versioned, validated contracts that let the copilot reason about goals and
plans without flattening broad directions into premature task lists.

# Scope

- Extend the canonical goal schema with optional fields for horizon, why,
  constraints, non-goals, review cadence, readiness, and links to active plans.
- Extend the canonical plan schema with desired outcome, success evidence,
  boundaries, assumptions, review date, milestones, and rolling-wave depth.
- Define typed milestone and near-term action models.
- Define a durable planning-session record that stores user answers, selected
  context references, decisions, and proposal links without storing hidden chain
  of thought.
- Define plan-option models including tradeoffs, risks, confidence labels,
  unresolved questions, source references, and rejected alternatives.
- Add schema-version compatibility and migration diagnostics.
- Update deterministic parsing, structural lint, registry indexing, typed facade,
  and bridge contracts.

# Out of scope

- Asking planning questions.
- Calling a language model.
- Generating plan options.
- Applying changes to goal or plan files.

# Required invariants

- Existing valid goal and plan notes remain valid or migrate conservatively.
- Optional unknown values remain unknown rather than receiving invented defaults.
- Stable goal, plan, milestone, action, and session IDs are collision-checked.
- Tasks remain embedded in their owning plans.
- Planning sessions reference canonical notes but do not become a second source
  of truth for approved plans.
- No schema field stores private model reasoning.

# Required tests

- Minimal and fully populated goal and plan notes.
- Legacy notes without new fields.
- Invalid horizons, statuses, dates, identifiers, and relationships.
- Duplicate milestone, action, and session IDs.
- Unknown versus empty versus not-applicable values.
- Schema upgrades and unsupported versions.
- Registry rebuild and shuffled file-order determinism.
- Python and TypeScript contract parity.

# Acceptance criteria

- Later copilot modules consume one typed contract layer.
- Existing vaults receive actionable diagnostics rather than destructive rewrites.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/markdown tests/registry tests/facade tests/bridge tests/planning -q
pytest -q
ruff check src tests
mypy src
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-005: Status and confidence
- DD-006: Stable IDs are selective
- DD-022: Goals are directions
- DD-023: Tasks stay with plans
- DD-033: SQLite disposability and rebuilding
