---
id: LIFEOS-1635
title: Make documentation impact a completion gate
status: in-progress
phase: 16
depends_on: []
risk: low
branch: lifeos-1635-documentation-impact-gate
---

# Goal

Prevent LifeOS code and user-visible behavior from advancing while repository documentation silently falls behind.

# Scope

- Require every implementation task to include a `# Documentation impact` section.
- Require that section to declare either `Status: required` or `Status: none`.
- Require a concrete reason when documentation impact is `none`.
- Update `AGENTS.md` completion rules so affected user, architecture, decision, setup, or operations documentation is reviewed before a task is completed.
- Add a CI guard that checks pull-request diffs for source changes and verifies the task's documentation-impact declaration plus corresponding documentation changes when required.
- Keep an explicit `none` escape hatch for internal changes that genuinely do not alter documented behavior or contracts.
- Create a separate backlog task to audit historical completed work for documentation debt.

# Out of scope

- Performing the historical documentation audit in this task.
- Rewriting all existing completed task files to the new format.
- Requiring docs changes for every internal refactor when the task explains why documentation is unaffected.

# Acceptance criteria

- `AGENTS.md` requires documentation-impact review before completion.
- `tasks/README.md` documents the mandatory section and syntax.
- CI fails when a source-changing PR has no valid task documentation-impact declaration.
- CI fails when `Status: none` has no reason.
- CI fails when `Status: required` is declared but no documentation file changed.
- CI passes for a justified `Status: none` case and for a required-docs case with documentation changes.
- The guard is covered by focused tests.
- A separate backlog task exists for historical documentation-debt cleanup.

# Documentation impact

Status: required

- `AGENTS.md`: make documentation review part of task completion.
- `tasks/README.md`: define the task-level documentation-impact contract.
- `.github/workflows/ci.yml`: add the automated documentation-impact gate.

# Validation

```bash
uv run pytest -q tests/project/test_documentation_impact.py
uv run ruff check .
uv run mypy src
uv run pytest -q
```
