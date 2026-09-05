---
id: LIFEOS-1719
title: Remove obsolete repository coding-agent prompts
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove the obsolete `prompts/` coding-agent convenience layer now that repository development workflow and authority are defined canonically by `AGENTS.md`, task contracts, architecture, and accepted design decisions.

# Scope

- Remove `prompts/bootstrap-repository.md`.
- Remove `prompts/implement-next-task.md`.
- Remove direct CI/documentation references that exist only to classify or describe the deleted `prompts/` tree.
- Verify no runtime or supported development workflow depends on those files.
- Keep repository task/workflow validation coherent after the removal.

# Out of scope

- Removing other potentially historical repository files without separate evidence and approval.
- Changing LifeOS runtime agent behavior, MCP instructions, vault bootstrap behavior, or user-facing capabilities.
- Refactoring unrelated CI or documentation-impact logic.

# Acceptance criteria

- Both obsolete files under `prompts/` are removed.
- Active repository documentation and CI classification no longer special-case the deleted `prompts/` tree.
- Repository inspection finds no supported runtime or workflow dependency on those prompt files.
- Development authority remains defined by `AGENTS.md` and repository source-of-truth documents.
- Task/workflow validation and project contract tests pass.

# Documentation impact

Status: required

- `README.md`: remove the obsolete `prompts/` example from the CI scope description while preserving the current development-authority guidance.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: explicit current-user instruction and repository authority/workflow rules govern implementation work.
- `docs/architecture.md`: application `AGENTS.md` governs development while runtime agent behavior is supplied through MCP and allowlisted vault instructions.
- `docs/design-decisions.md` DD-079: application-repository development concerns are separate from agent-assisted runtime ingestion.

# Completion notes

- Removed both files under `prompts/`; the empty directory therefore disappears from the repository tree.
- Removed the deleted tree's special-case entry from `scripts/check_documentation_impact.py`, its synthetic `prompts/system.md` test assertion, and the README CI-scope reference.
- Repository inspection found no supported LifeOS runtime consumer of these coding-agent convenience prompts; current development authority remains in `AGENTS.md` and repository source-of-truth documents.
- Local validation could not run in the execution environment because `github.com` DNS resolution was unavailable; no local test pass is claimed.
- PR #58 `fast-checks` and `obsidian-plugin` passed on head `69d394c20f3a52201e2794b76c8edd952bc49be9`, including task workflow validation, documentation impact, manual links, Ruff, mypy, compilation, test collection, project contract smoke tests, and plugin lint/typecheck/tests/build.
- Codex review of the implementation head `73ff7f271da368e36e09d9e5b90dbee848a8c718` reported no major issues. Later commits only recorded independent follow-up backlog tasks and did not change implementation behavior.
- Discovered independent cleanup/documentation work was recorded as LIFEOS-1720 through LIFEOS-1723 rather than widening this task.
