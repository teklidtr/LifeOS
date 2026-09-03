---
id: LIFEOS-1701
title: Add canonical personal-pattern artifact contract
status: completed
phase: 17
depends_on:
  - LIFEOS-1700
risk: high
---

# Goal

Create a strict, portable canonical contract for individual personal working hypotheses under `patterns/`.

# Scope

- Add `pattern_schema: 1` and `type: pattern` with stable identity.
- Reuse standard `status`, `confidence`, and `review_reasons` fields.
- Support a concise hypothesis statement, origin, timestamps, evidence references, supporting/contesting/contextual evidence roles, source hashes, evidence fingerprint, review timing, and optional deterministic evaluation recipe.
- Separate machine-managed evidence summaries from human-owned reflection.
- Parse and validate pattern artifacts.
- Reject duplicate IDs, malformed evidence references, unsafe paths, invalid hashes, and unsupported schemas.
- Leave ordinary Markdown in `patterns/` without a recognized schema untouched.

# Out of scope

- Generating patterns.
- Lifecycle transitions.
- Evidence re-evaluation.
- Personal Model indexing.
- Planner integration.

# Required invariants

- `active` means accepted as a useful working hypothesis, not established truth.
- `needs-review` is used for materially unresolved evidence changes.
- Staleness and contradiction remain review reasons rather than new exclusive statuses.
- Confidence is not a numeric model probability.
- Human-owned prose is preserved outside managed regions.

# Acceptance criteria

- Canonical patterns round-trip deterministically.
- Malformed patterns fail with typed diagnostics.
- Existing unrelated notes under `patterns/` remain usable.
- Pattern parsing does not require disposable runtime state.
- Focused tests cover all lifecycle states, counter-evidence, malformed hashes/paths, duplicate IDs, unsupported schemas, and human-owned content preservation.

# Documentation impact

Status: required

- `docs/data-model.md`: document `pattern_schema: 1`.
- `docs/personal-model-architecture.md`: finalize artifact semantics.
- `docs/user-manual/03-feature-breakdown.md`: introduce canonical working hypotheses.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-001
- DD-005
- DD-006
- DD-009
- DD-011
- DD-012
- Phase 17 Personal Model architecture

# Validation evidence

- PR #41 fast-check workflow run `33806305587` passed on implementation head `65509dde785b75c407bf80dbeb44d3a37c3cc829`, including the documentation-impact gate, manual-link validation, Ruff, mypy, Python compilation, pytest collection, and repository contract smoke tests.
- PR #41 full-validation workflow run `33806318935` passed on the same implementation head. All four full pytest shards passed, including the focused pattern lifecycle, counter-evidence, malformed hash/path, duplicate identity, unsupported schema, LF/CRLF round-trip, and human-owned preservation coverage. The clean-room setup/MCP gate, home-node service container gate, and ARM64 home-node image build also passed.
- The initial full-validation run exposed two serializer preservation defects at the managed-block boundary. Commit `95a1dfa3008cc1a9c9a0fdd801139289edfd82e0` made the frontmatter closing newline structural serializer output, and commit `65509dde785b75c407bf80dbeb44d3a37c3cc829` preserved CRLF suffix boundaries without changing the shared Markdown parser. The subsequent full validation passed.
- An exact local checkout for `git diff --check` could not be obtained because the execution environment could not resolve `github.com`. This is an environment limitation rather than a validation pass. The closest practical substitute was a GitHub PR unified-diff audit; no trailing-whitespace error or unintended scope change was found.
- Security review and code review were explicitly skipped by the repository owner for this task. Required validation and merge-readiness checks were not waived.
