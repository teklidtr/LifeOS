---
id: LIFEOS-1008
title: Add study-session controls to the Obsidian dashboard
status: completed
phase: 10
depends_on:
  - LIFEOS-1003
  - LIFEOS-1004
  - LIFEOS-1006
risk: medium
---

# Goal

Turn deterministic study workloads into an Obsidian-native review session that
records meaningful session outcomes without creating one task per flashcard.

# Scope

- Add a Today dashboard study card showing due workload, estimated duration,
  topics, overdue counts, and omitted cards.
- Let the user choose a time budget and optional topic filter.
- Add **Start session**, **Pause**, **Resume**, **Finish**, and **Abandon**
  interactions.
- Present cards or source links using canonical Markdown content.
- Record session-level actual time and outcome.
- Record card-level review evidence only if a canonical scheduling contract is
  explicitly defined; otherwise keep v1 session-level.
- Reconcile interrupted sessions through the attention engine.
- Link the session result to source refs and the day's journal or execution
  history.
- Keep selection and ordering in the Python study service.

# Out of scope

- Replacing a dedicated spaced-repetition algorithm.
- Remote flashcard services.
- One dashboard task per card.
- AI grading of free-text answers.
- Mobile plugin parity.

# Required invariants

- The UI displays the exact deterministic workload selected by Python.
- Starting a session does not mutate card due dates unless a defined review
  result is recorded.
- An interrupted session remains distinguishable from a completed one.
- Card source references remain inspectable.
- Session retries do not duplicate history.

# Required tests

- Empty, small, overdue, and over-capacity workloads.
- Topic filter and time-budget changes.
- Start, pause, resume, finish, and abandon lifecycle.
- Plugin reload during an active session.
- Source note changed or removed during a session.
- Reconciliation of an unfinished session.
- Keyboard navigation and screen-reader labels.

# Acceptance criteria

- A study session can be selected, run, and closed entirely in Obsidian.
- Workload semantics remain consistent with LIFEOS-400 and LIFEOS-905.
- No per-card task explosion is introduced.
- Python and plugin tests pass.

# Validation commands

```bash
pytest tests/study tests/daily tests/attention tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-017: Original sources remain immutable
- DD-024: Flashcards are workload sessions
- DD-033: SQLite disposability and rebuilding
