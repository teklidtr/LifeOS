---
id: LIFEOS-1704
title: Add pattern re-evaluation and review triggers
status: completed
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

# Validation evidence

- PR #44 fast-check workflow run `33846966336` passed on implementation head `ac1d685bc771ec1ecbd7df39917804789502b5d0`, including the documentation-impact gate, manual-link validation, Ruff, mypy, Python compilation, pytest collection, and repository contract smoke tests.
- PR #44 full-validation workflow run `33847016366` passed on the same implementation head. All four full pytest shards and aggregate `full-test` passed; the clean-room/MCP gate, home-node service-container gate, and ARM64 home-node image build also passed.
- The first fast-check run exposed two mypy tuple-inference errors in the new review implementation. They were fixed before the successful fast-check and full-validation runs above.
- An exact local checkout could not be obtained because the execution environment could not resolve `github.com`; this is an environment limitation rather than a validation pass. Consequently the task-listed local `git diff --check` command could not be executed directly. The closest practical substitute was a GitHub master-to-branch compare plus PR patch audit, with no visible whitespace-error finding.
- Code-review/Codex review and security review were explicitly skipped by the repository owner for this task. Full validation and merge-readiness checks were not waived.
