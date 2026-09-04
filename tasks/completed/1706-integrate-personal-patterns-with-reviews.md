---
id: LIFEOS-1706
title: Integrate personal patterns with daily and weekly reviews
status: completed
phase: 17
depends_on:
  - LIFEOS-1704
  - LIFEOS-1705
risk: medium
---

# Goal

Make personal hypotheses maintainable over time without turning reviews into an obligation queue.

# Scope

- Add bounded pattern evidence to review snapshots.
- Weekly review may surface new seeds, materially changed active patterns, due patterns, needs-review patterns, and unresolved contesting evidence.
- Daily review may surface only urgent or explicitly pinned pattern review items.
- Reuse evidence fingerprints and existing review-item decisions.
- Support acknowledge, defer, open source, propose change, and dismiss-unchanged actions.
- Suppress unchanged dismissed prompts until their evidence fingerprint changes.

# Out of scope

- Monthly or quarterly review kinds.
- Forcing every active pattern into every weekly review.
- Automatic pattern mutation on review completion.

# Required invariants

- Reviews surface choices, not obligations.
- Unchanged dismissed evidence does not repeatedly nag.
- Changed evidence creates a new review context.
- Completing a review does not imply agreement with a pattern.

# Acceptance criteria

- Pattern maintenance fits existing canonical review architecture.
- Review artifacts preserve decisions and evidence fingerprints.
- Selection is bounded and optional.
- Tests cover empty state, due patterns, many-pattern bounds, dismissal suppression, changed evidence resurfacing, daily suppression, and proposal creation.

# Documentation impact

Status: completed

- `docs/review-artifact-architecture.md`: pattern review evidence documented.
- `docs/user-manual/10-first-class-reviews.md`: pattern workflow documented.
- `docs/personal-model-architecture.md`: review integration documented.

# Validation

- Current implementation head passed `fast-checks`, including Ruff, mypy, Python compilation, test collection, and project contract smoke tests.
- Full-validation run `33863082297` passed on implementation head `3feb7bb211181edefa79df96ab3d3f1134a6d576`: all four full pytest shards passed, aggregate `full-test` passed, and `docker-setup-e2e` passed.
- Two Codex review rounds were completed. All actionable review threads were addressed and resolved. Security review was intentionally skipped per user instruction.
- This task-completion move changes only task metadata/path; repository workflow requires a fresh current-head `fast-checks` and full-validation checkpoint before merge, so those checks are rerun after this commit.

Local validation limitation: the available execution container could not resolve `github.com`, so the branch could not be cloned into the local runtime. Repository-wide seam/invariant audits were used as the closest practical local substitute, with deterministic behavioral validation performed by GitHub CI as explicitly documented in the PR.

# Relevant design decisions

- DD-055
- DD-056
- DD-057
- DD-058
- DD-059
