---
id: LIFEOS-1704
title: Add pattern re-evaluation and review triggers
status: in-progress
phase: 17
depends_on:
  - LIFEOS-1702
  - LIFEOS-1703
risk: high
---

# Goal

Detect when a working hypothesis deserves another look without silently deciding whether it remains valid.

# Scope

- Re-evaluate deterministic patterns that declare a supported evaluation recipe.
- Initially support existing observation forms such as numeric metric association and activity-versus-outcome comparison.
- Compare new analysis with the last reviewed evidence fingerprint.
- Detect materially new evidence, changed evidence, weaker evidence, direction reversal, new counter-evidence, stale evidence, and due review dates.
- Produce a review recommendation.
- Create a draft change proposal only after explicit user action.
- For semantic/manual patterns without deterministic recipes, limit automation to factual evidence-state and due-review detection.

# Out of scope

- Autonomous semantic contradiction discovery across the whole vault.
- Automatically changing confidence or lifecycle state.
- Medical interpretation.
- Treating absence of new data as contradiction.

# Required invariants

- Recalculation and semantic judgment are separate.
- Deterministic analysis may report changed direction but not declare a belief false.
- New evidence cannot rewrite the reviewed statement.
- Unknown remains unknown.

# Acceptance criteria

- LifeOS explains exactly why a pattern is due for review.
- No review trigger mutates canonical Markdown.
- Existing cautious observation semantics are preserved.
- Tests cover same-direction growth, weaker evidence, reversal, changed/missing sources, no new evidence, due review, and manual patterns.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document re-evaluation rules.
- `docs/user-manual/`: explain review triggers and counter-evidence.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-015
- DD-016
- DD-026
- DD-041
- DD-058
- Phase 17 Personal Model architecture
