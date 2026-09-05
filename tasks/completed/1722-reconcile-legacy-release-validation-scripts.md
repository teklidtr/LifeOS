---
id: LIFEOS-1722
title: Reconcile legacy release validation scripts
status: completed
phase: hardening
depends_on: []
risk: medium
---

# Goal

Determine whether the repository's older manual release-validation/build script chain still represents the current release contract now that PR/full-validation CI covers a broader system and later feature slices have their own historical validators.

# Scope

- Audit `scripts/validate-release.sh`, `scripts/build-release.sh`, and feature-specific validation scripts against current CI, supported packaging, and release documentation.
- Identify which scripts remain supported entry points versus historical one-off release gates.
- Remove or consolidate redundant scripts only after preserving any guarantees that are not covered elsewhere.
- Ensure any retained release command validates the current product surface rather than stopping at older feature phases.

# Out of scope

- Changing product behavior merely to satisfy an old validation script.
- Weakening current `fast-checks`, `obsidian-plugin`, or `full-validation` guarantees.
- Deleting historical task records.

# Acceptance criteria

- Every retained release/build script has a documented current purpose and caller.
- Historical feature validators with no supported caller are removed or explicitly retained with a non-authoritative purpose.
- The supported release path covers the current package/plugin/runtime contract or delegates to the current authoritative validation path.
- Tests and documentation identify a single understandable release-validation story.

# Documentation impact

Status: required

- Review README/setup/release documentation for any supported manual release entry point.
- Document the retained release-validation path or remove stale references together with retired scripts.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- run the retained release-validation entry point(s)
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: CI is an independent verification layer; full-validation is the final broad checkpoint.
- Current GitHub workflows: `fast-checks`, `obsidian-plugin`, and labeled `full-validation` are the active PR validation layers.

# Completion evidence

- Retired the unsupported aggregate `scripts/validate-release.sh` and `scripts/build-release.sh` chain together with the orphaned `validate-first-class-reviews.sh`, `validate-semantic-retrieval.sh`, and `validate-personal-experiments.sh` historical feature gates.
- Retained `scripts/validate-rich-capture.sh` because `docs/rich-capture-testing.md` still calls it as a focused local regression helper; the documentation now explicitly states that it is non-authoritative and does not replace the repository merge-readiness contract.
- Preserved guarantees unique to the retired scripts in `tests/project/test_release_validation_contract.py`, including package/plugin/protocol/runtime version compatibility, historical schema guards, provider-neutrality guards, absence of the retired scripts, and documentation of the authoritative validation path.
- Reviewed the README, setup/user-manual surface, architecture, design decisions, current workflows, and project CI contracts. The supported release/readiness story is the current `fast-checks` plus `obsidian-plugin` plus explicit `full-validation` path; no supported ZIP release consumer or caller for the retired build script was found.
- PR #61 `PR checks` run `33979974157` passed on head `98a2bd0d58ec9796389097148cd445f2838564b3`, including task workflow validation, documentation-impact gate, manual-link validation, Ruff, mypy, Python compilation, pytest collection, `tests/project`, and the Obsidian plugin checkpoint.
- PR #61 `Full validation` run `33980508857` passed on head `98a2bd0d58ec9796389097148cd445f2838564b3`, including all four full pytest shards, the aggregate `full-test` gate, clean-room setup/MCP validation, home-node service-container validation, and ARM64 home-node image build.
- Direct local checkout was unavailable because this execution environment could not resolve `github.com`; validation therefore used exact GitHub branch/compare inspection, local syntax checking for the new project contract test, and the repository's GitHub Actions gates rather than claiming unavailable local commands passed.
- A normal `@codex review` was requested after the implementation stabilized, but Codex reported that the account had reached its code-review usage limit and produced no review. On 2026-09-05 the user explicitly instructed the implementation agent to skip Codex review for LIFEOS-1722, overriding that review requirement for this task.
- Security review was skipped per the user's explicit instruction for this development sequence.
- No independent follow-up work was discovered that required a new backlog task.
