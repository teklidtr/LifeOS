---
id: LIFEOS-1710
title: Validate, recover, migrate, and document the Personal Model
status: completed
phase: 17
depends_on:
  - LIFEOS-1701
  - LIFEOS-1702
  - LIFEOS-1703
  - LIFEOS-1704
  - LIFEOS-1705
  - LIFEOS-1706
  - LIFEOS-1707
  - LIFEOS-1708
  - LIFEOS-1709
risk: high
---

# Goal

Ship Phase 17 as a coherent recoverable feature with conservative migration, end-to-end fixtures, and complete user documentation.

# Scope

- Add runtime deletion/rebuild coverage.
- Add proposal interruption/recovery coverage.
- Add representative histories for stable, weakening, contradicting, stale, archived, and sparse-evidence hypotheses.
- Add bounded large-vault performance fixtures.
- Handle existing Markdown under `patterns/` conservatively and do not auto-convert unrecognized user-authored notes.
- Add migration preview only if a recognizable legacy contract exists.
- Add end-to-end Obsidian lifecycle coverage.
- Add local STDIO MCP and authenticated home-node coverage where relevant.
- Complete user manual and roadmap shipped-state documentation.

# Out of scope

- Habits.
- Calendar.
- Monthly or quarterly reviews.
- Direct planner ranking changes.
- Web client work.
- Broad refactors unrelated to Phase 17.

# Required invariants

- Removing disposable Personal Model state cannot remove canonical patterns.
- Migration never invents semantic status or confidence.
- Existing human Markdown is not silently rewritten.
- Recovery preserves proposal and evidence lineage.
- Release fixtures contain no hidden universal score.

# Acceptance criteria

- Phase 17 works end to end from evidence through proposal, canonical hypothesis, review, re-evaluation, context, and Obsidian inspection.
- `.lifeos/` may be removed and rebuilt without losing Personal Model knowledge.
- Existing arbitrary `patterns/` Markdown remains untouched unless explicitly migrated.
- Full repository validation passes.
- User documentation states clearly that personal patterns are working hypotheses, not truths or diagnoses.

# Documentation impact

Status: required

- `docs/roadmap.md`: mark Phase 17 shipped after completion.
- `docs/user-manual/README.md`: add the Personal Model chapter.
- `docs/user-manual/`: add the complete Personal Model workflow chapter.
- `docs/user-manual/03-feature-breakdown.md`: add the final feature summary.
- `docs/user-manual/06-obsidian-desktop.md`: document final workspace behavior.
- `docs/personal-model-architecture.md`: reconcile shipped contracts.
- `README.md`: mention the evidence-backed Personal Model if appropriate.

# Validation commands

- `python3 scripts/validate_manual_links.py`
- `pytest -q`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- All accepted Phase 17 Personal Model decisions
- AGENTS.md completion and review rules

# Completion evidence

- PR: #50, `LIFEOS-1710 Validate and document the Personal Model release`.
- Added release-level Personal Model fixtures for representative lifecycle/evidence histories, real `.lifeos/` deletion and rebuild, proposal interruption/rollback with proposal and evidence-lineage preservation, arbitrary unrecognized `patterns/` Markdown preservation, bounded large-vault behavior, and evidence-to-Obsidian end-to-end lifecycle behavior.
- The bounded large-vault fixture creates 192 canonical patterns plus 768 ordinary `patterns/` notes and enforces a 5-second first-rebuild budget; CI observed the fixture well inside that bound.
- Existing local STDIO and authenticated home-node MCP regressions continue to verify that Personal Model agent tools are draft-only and that the remote surface excludes proposal approval/application authority.
- No recognizable pre-Phase-17 canonical Personal Model migration contract exists. Release documentation therefore records the conservative behavior: legacy-looking Markdown without the recognized `pattern_schema` remains ordinary user-authored Markdown and is not heuristically converted.
- Added `docs/user-manual/19-personal-model.md` and reconciled README, manual navigation, feature breakdown, roadmap, and Personal Model architecture documentation.
- The current repository added LIFEOS-1712 through LIFEOS-1715 as later `phase: 17` capability-discoverability work while LIFEOS-1710 was in progress. Current repo authority therefore supersedes the older task wording that implied LIFEOS-1710 closes all of Phase 17: this task completes the Personal Model release slice, while the roadmap correctly keeps Phase 17 open for those later tasks.
- Independent duplicate task-ID debt was recorded separately as LIFEOS-1716 instead of widening this task.
- Local repository execution was unavailable in the agent environment because there was no mounted checkout and the container could not resolve `github.com`; repository-wide static API/seam audits were used as the required closest practical substitute before CI.
- Normal Codex review was requested once after a green fast-check and invariant audit. Its single P2 finding was addressed by correcting premature shipped-state wording and adding Personal Model-specific runtime-deletion and proposal-interruption/recovery fixtures. The review thread was resolved; no second paid review was required because the fixes were tests/documentation rather than a material runtime or trust-boundary change.
- Security review was skipped under the repository owner's explicit instruction for this task.
- Full validation exposed a pre-existing nondeterministic LIFEOS-1709 test fixture whose fixed lifecycle timestamps could precede the proposal's real wall-clock creation time. The test-only helper was corrected to derive lifecycle timestamps from canonical proposal `created_at`; repository runtime behavior was unchanged.
- Full validation then exposed that the new release E2E fixture had omitted the canonical `patterns/` root. The fixture was corrected rather than weakening proposal preflight, preserving the fail-closed rule that proposal application does not invent missing canonical roots.
- `fast-checks` run `33917082978` passed on release-validation head `73a328984d92331b436bb309338c36ca960b4755`, including documentation impact, manual links, Ruff, mypy, compilation, collection, and project contract smoke tests.
- Authoritative full-validation run `33917151883` passed on the same release-validation head. All four pytest shards passed, aggregate `full-test` passed, and `docker-setup-e2e` passed clean-room setup/MCP, authenticated home-node service-container, and ARM64 image-build gates.
- The task is moved to `completed` only after those acceptance, documentation, review, and full-validation gates were green.
