---
id: LIFEOS-1706
title: Integrate personal patterns with daily and weekly reviews
status: in-progress
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

Status: required

- `docs/review-artifact-architecture.md`: add pattern review evidence.
- `docs/user-manual/10-first-class-reviews.md`: document the pattern workflow.
- `docs/personal-model-architecture.md`: document review integration.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

Local validation limitation: the available execution container cannot resolve `github.com`, so the branch cannot be cloned into the local runtime and the listed commands cannot be executed there. The closest practical pre-push substitute was a repository-wide static seam audit of every changed shared call shape (`build_review_snapshot`, `refresh_review_snapshot`, and `open_daily_review`), review/proposal invariants, and the complete branch diff. Required deterministic validation is therefore left explicitly to GitHub CI rather than treated as locally passed.

# Relevant design decisions

- DD-055
- DD-056
- DD-057
- DD-058
- DD-059
