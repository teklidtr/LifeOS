---
id: LIFEOS-1202
title: Build planning-readiness diagnostics and bounded context assembly
status: backlog
phase: 12
depends_on:
  - LIFEOS-1200
  - LIFEOS-1201
  - LIFEOS-300
risk: high
---

# Goal

Determine whether a goal is ready for planning and assemble the smallest useful,
inspectable context pack for a goal-to-plan session.

# Scope

- Add deterministic readiness checks for goal identity, horizon, purpose,
  constraints, desired change, active-plan links, review state, and unresolved
  contradictions.
- Distinguish hard blockers, useful clarification questions, optional enrichment,
  and information that should not be requested.
- Assemble bounded context from the selected goal, linked plans, explicit
  blockers, recent relevant reviews, current planning preferences, available
  capacity, and user-selected supporting notes.
- Add explicit include, exclude, preview, and redaction controls.
- Reuse context-pack routing without requiring semantic retrieval.
- Record source IDs, hashes, truncation, omissions, and freshness diagnostics.
- Expose read-only facade and bridge operations.

# Out of scope

- General vault conversation.
- Automatic broad searches through journals or health notes.
- Goal clarification dialogue.
- Plan generation.
- Canonical writes.

# Required invariants

- Context inclusion is explainable and scope-limited.
- Sensitive folders are excluded unless explicitly permitted by policy and user
  action.
- Missing information becomes a question or diagnostic, not an invented fact.
- Context packs are disposable and rebuildable.
- A user can inspect exactly what will be sent before model invocation.
- The workflow remains usable with only explicit links and lexical routing.

# Required tests

- Ready, incomplete, contradictory, archived, and already-covered goals.
- Goals with zero, one, and several active plans.
- Explicit include and exclude controls.
- Sensitive-scope denial and redaction.
- Stale, moved, deleted, and concurrently edited source notes.
- Context-size truncation with stable ordering and omission reports.
- No semantic backend configured.
- Determinism under shuffled registry order.

# Acceptance criteria

- The copilot can explain why a goal is or is not ready.
- Every model-bound context item is previewable and traceable.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/context tests/planning tests/facade tests/bridge tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-009: Explicit instruction authority
- DD-014: Context packs use multiple retrieval modes
- DD-022: Goals are directions
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
