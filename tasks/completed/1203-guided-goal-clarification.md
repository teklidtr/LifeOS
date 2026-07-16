---
id: LIFEOS-1203
title: Implement guided goal clarification sessions
status: completed
phase: 12
depends_on:
  - LIFEOS-1201
  - LIFEOS-1202
  - LIFEOS-114
risk: high
---

# Goal

Help the user clarify an incomplete goal through a short, adaptive conversation
that can also conclude that no plan should be created yet.

# Scope

- Add typed clarification-question categories for purpose, desired change,
  horizon, constraints, non-goals, success evidence, uncertainty, tradeoffs, and
  current commitments.
- Use deterministic readiness diagnostics to choose mandatory questions before
  optional agent-generated questions.
- Ask one focused question at a time and support skip, unknown, not relevant,
  save draft, resume, and stop actions.
- Offer explicit session outcomes: ready to plan, run a small experiment, park,
  continue reflecting, link an existing plan, or abandon the session.
- Persist user answers and explicit decisions in the planning-session record.
- Validate model output against a strict schema and fall back to deterministic
  questions when unavailable or invalid.
- Add facade and bridge operations for session start, answer, resume, and close.

# Out of scope

- Generating a complete plan.
- Editing the canonical goal automatically.
- Inferring hidden motives or diagnosing avoidance.
- Open-ended therapy or coaching chat.

# Required invariants

- The user may stop without creating a plan.
- Skipped questions do not become negative answers.
- Agent questions are visibly suggestions, not requirements.
- The system never invents a deadline, priority, or personal motive.
- Session state is recoverable and does not silently alter canonical notes.
- No hidden model reasoning is stored.

# Required tests

- Deterministic-only and model-assisted sessions.
- Incomplete, conflicted, already-ready, and archived goals.
- Skip, unknown, resume, cancel, and abandon paths.
- Invalid, irrelevant, repetitive, and unsafe model questions.
- Model timeout and unavailable-provider fallback.
- Session-schema upgrade and crash recovery.
- Concurrent edits to the source goal during a session.

# Acceptance criteria

- A user can reach a clear next decision without being forced into plan creation.
- Every stored answer is user-visible and editable.
- Full tests, lint, type checks, and diff checks pass.

# Validation commands

```bash
pytest tests/planning tests/ai tests/facade tests/bridge tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-005: Status and confidence
- DD-022: Goals are directions
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
