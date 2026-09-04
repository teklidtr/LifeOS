---
id: LIFEOS-1708
title: Build the Obsidian Personal Model workspace
status: completed
phase: 17
depends_on:
  - LIFEOS-1703
  - LIFEOS-1704
  - LIFEOS-1705
  - LIFEOS-1706
risk: medium
---

# Goal

Give the user an Obsidian-native surface for inspecting and maintaining working hypotheses without editing YAML or using terminal commands.

# Scope

- Add a dockable Personal Model workspace with Active, Needs review, Seeds, and Archived views.
- Show hypothesis statement, confidence, evidence health, review reasons, and freshness.
- Open supporting and contesting canonical sources.
- Show evidence changes since the last review.
- Support proposal-backed Track, Adopt, Revise, Contest, and Archive actions.
- Link to relevant reviews and experiments.
- Provide empty, degraded, stale, and blocked states.
- Preserve keyboard navigation and accessibility.

# Out of scope

- Personality dashboards.
- Gamification or scores.
- Automatic suggestions on every startup.
- Direct Markdown mutation in TypeScript.

# Required invariants

- Python remains the sole business-rule engine.
- UI refresh is read-only.
- Consequential actions produce proposals.
- Evidence is visible before adoption or revision.
- Missing runtime state degrades to rebuild/recovery rather than data loss.

# Acceptance criteria

- A user can understand why a pattern deserves attention and inspect its evidence.
- Normal pattern review requires no terminal command.
- No pattern can be silently changed from the plugin.
- Tests cover empty/mixed states, evidence navigation, proposal preview, stale target, runtime rebuild, keyboard workflow, screen-reader labels, and text scaling.

# Documentation impact

Status: required

- `docs/user-manual/06-obsidian-desktop.md`: document the Personal Model workspace.
- `docs/user-manual/`: add the Phase 17 user workflow.
- `docs/personal-model-architecture.md`: document the bridge/UI boundary.

# Validation commands

- `pytest -q`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Validation

- Ordinary PR `fast-checks` passed repeatedly during implementation; post-review UI fixes passed run `33891478048` on head `ca1fb4d9257d7e86bfdb4575c86e367eef148c56`.
- Pre-review full-validation run `33890221080` passed on trust-boundary consolidation head `45eaa161606bd56dd4d2e8aa8210fe7ca8416c67`: all four full pytest shards passed, aggregate `full-test` passed, and `docker-setup-e2e` passed including the home-node and ARM64 image gates.
- The execution container could not resolve `github.com`, so the repository could not be materialized locally. To avoid silently skipping the task's explicit Node checks, a temporary workflow-only validation commit ran the current implementation through `npm --prefix packages/obsidian-plugin ci`, `npm --prefix packages/obsidian-plugin test`, `npm --prefix packages/obsidian-plugin run typecheck`, and `git diff --check`; PR-check run `33891758114` passed all of those steps plus Ruff, mypy, compilation, collection, and project smoke tests. The temporary workflow edit was then restored byte-for-byte to the master version and is not part of the final PR diff.
- Four normal Codex review rounds were completed on implementation snapshots. All actionable findings were implemented by the current implementation agent, covered with regressions where appropriate, and all review threads were resolved. The final review's two localized P2 UI-state findings were fixed and validated deterministically without starting another mechanical review cycle.
- Security review was intentionally skipped per the user's explicit instruction.
- The missing permanent Obsidian plugin CI checkpoint discovered during this task is captured separately as `LIFEOS-1711`; it is independent infrastructure work and does not expand this task's product scope.
- This task-completion move changes task metadata/path after the implementation validations above. Repository workflow therefore requires a fresh current-head `fast-checks` and final `full-validation` checkpoint before merge.

# Relevant design decisions

- DD-036
- DD-037
- DD-038
- DD-080
- Phase 17 Personal Model architecture
