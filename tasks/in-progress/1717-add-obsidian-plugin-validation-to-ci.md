---
id: LIFEOS-1717
title: Add Obsidian plugin validation to CI
status: in-progress
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

# Relevant design decisions

- DD-037
- DD-080
