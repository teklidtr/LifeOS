---
id: LIFEOS-1719
title: Remove obsolete repository coding-agent prompts
status: ready
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove the obsolete `prompts/` coding-agent convenience layer now that repository development workflow and authority are defined canonically by `AGENTS.md`, task contracts, architecture, and accepted design decisions.

# Scope

- Remove `prompts/bootstrap-repository.md`.
- Remove `prompts/implement-next-task.md`.
- Verify no runtime or supported development workflow depends on those files.
- Keep repository task/workflow validation coherent after the removal.

# Out of scope

- Removing other potentially historical repository files without separate evidence and approval.
- Changing LifeOS runtime agent behavior, MCP instructions, vault bootstrap behavior, or user-facing capabilities.
- Refactoring unrelated CI or documentation-impact logic.

# Acceptance criteria

- Both obsolete files under `prompts/` are removed.
- Repository search finds no supported runtime or workflow dependency on those prompt files.
- Development authority remains defined by `AGENTS.md` and repository source-of-truth documents.
- Task/workflow validation and project contract tests pass.

# Documentation impact

Status: none
Reason: This removes obsolete repository-maintainer convenience prompts without changing LifeOS user-visible behavior, architecture, runtime contracts, setup, CLI, MCP behavior, or documented development authority.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: explicit current-user instruction and repository authority/workflow rules govern implementation work.
- `docs/architecture.md`: application `AGENTS.md` governs development while runtime agent behavior is supplied through MCP and allowlisted vault instructions.
- `docs/design-decisions.md` DD-079: application-repository development concerns are separate from agent-assisted runtime ingestion.
