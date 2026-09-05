---
id: LIFEOS-1717
title: Add Obsidian plugin validation to CI
status: completed
phase: 17
depends_on:
  - LIFEOS-1708
risk: medium
---

# Goal

Make Obsidian plugin regressions fail deterministically in repository CI instead of relying on an implementation agent having a runnable local Node environment.

# Scope

- Add a CI checkpoint for changes that can affect `packages/obsidian-plugin/`.
- Install plugin dependencies from the committed lockfile with the repository-supported Node/npm version.
- Run the plugin typecheck and test suite in CI.
- Include the plugin lint/build checks when they are part of the repository's supported plugin validation contract.
- Make the final pull-request validation workflow expose a clear green/red plugin result for the current PR head.
- Keep docs-only changes eligible for the existing lightweight path when plugin validation is irrelevant.

# Out of scope

- Changing Personal Model product behavior.
- Refactoring plugin runtime architecture.
- Replacing npm or the existing plugin build toolchain.
- Adding browser automation or Obsidian end-to-end coverage beyond the current deterministic plugin contract.

# Required invariants

- CI validates the exact current PR head.
- Plugin validation uses the committed dependency lockfile.
- A skipped plugin check is explicit and scope-driven rather than silently treated as passing.
- Python and Docker validation remain independent checkpoints rather than being weakened to make room for plugin CI.

# Acceptance criteria

- A pull request that introduces a failing Obsidian plugin unit test fails CI.
- A pull request that introduces a TypeScript type error in the plugin fails CI.
- The repository documents which plugin checks are required before merge.
- CI output makes it obvious whether plugin validation ran, passed, failed, or was legitimately skipped.

# Documentation impact

Status: required

- `AGENTS.md`: document the required Obsidian plugin CI checkpoint in the pull-request validation workflow.

# Validation commands

- `npm --prefix packages/obsidian-plugin ci`
- `npm --prefix packages/obsidian-plugin run lint`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run build`
- `pytest -q tests/project`
- `git diff --check`

# Validation

- PR #56 `PR checks` run `33954589265` passed on implementation head `d8b4b316a4b8bbd81103f99a9baa14f6750b1ad2`.
- The dedicated `obsidian-plugin` job checked out `github.event.pull_request.head.sha` and passed `npm --prefix packages/obsidian-plugin ci`, lint, typecheck, unit tests, and build. The documentation-only skip step was present but correctly skipped for this implementation-changing PR.
- The independent `fast-checks` job passed task workflow validation, documentation impact, manual links, Ruff, mypy, compilation, full test collection, and `pytest -q tests/project` on the same head.
- A fresh local checkout remained unavailable because the execution environment could not resolve `github.com`. Per `AGENTS.md`, unavailable local execution was not represented as a pass. The branch diff, workflow structure, exact-head checkout, scope-classification seam, YAML shape, and added-line whitespace were audited statically before CI; repository CI supplied the executable Node and project-test validation layer.
- The exact local `git diff --check` command could not be run without a checkout. The GitHub PR diff was inspected for whitespace errors as the closest static substitute; the final completion head still requires fresh CI before merge.
- Normal Codex review completed against `d8b4b316a4` and reported no major issues. No review threads require changes.
- Security review was intentionally skipped per the user's explicit instruction.
- `docs/user-manual/` and `docs/obsidian-desktop-architecture.md` were reviewed. No user-facing workflow or runtime architecture changed; `AGENTS.md` and the existing maintainer CI documentation in `README.md` were updated instead.
- No newly discovered independent implementation work required an additional backlog task. Existing LIFEOS-1718 remains separate historical task-metadata reconciliation work.
- This completion move changes the task path/status after the implementation validations above. Repository workflow therefore requires fresh current-head `fast-checks` and `obsidian-plugin` results plus the final `full-validation` checkpoint before merge.

# Relevant design decisions

- DD-037
- DD-080
