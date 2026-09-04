---
id: LIFEOS-1716
title: Reconcile the duplicate LIFEOS-1711 task ID
status: in-progress
phase: hardening
depends_on: []
risk: low
---

# Goal

Restore global task-ID uniqueness after a newly added Phase 17 backlog task reused the already-completed `LIFEOS-1711` identifier.

# Problem and evidence

The repository currently contains two distinct task contracts with `id: LIFEOS-1711`:

- `tasks/completed/1711-distinguish-missing-and-unsafe-ownership-manifests-at-consumers.md`, which is completed historical work;
- `tasks/backlog/1711-add-obsidian-plugin-validation-to-ci.md`, which is an unrelated future CI task.

Completed task identity is implementation history and must not be reassigned. The backlog CI task therefore needs a new unique task ID and filename, with any dependency or documentation references updated consistently.

# Scope

- Choose the next repository-valid unique ID for the backlog Obsidian plugin CI task.
- Rename that backlog task file and update its frontmatter ID without changing its product scope or acceptance criteria.
- Update repository references that specifically point to the duplicated backlog task ID.
- Add or strengthen deterministic task validation only if the existing task workflow does not already detect duplicate IDs.

# Out of scope

- Implementing the Obsidian plugin CI task itself.
- Changing the completed ownership-manifest task or its historical completion evidence.
- Renumbering unrelated Phase 17 capability-discoverability tasks.
- Product, architecture, or runtime behavior changes.

# Required invariants

- Completed task IDs remain immutable historical identities.
- Every active and completed task contract has a unique `id` after the repair.
- Dependency references continue to point at the intended task after any rename.
- The CI task's original scope and acceptance criteria remain unchanged apart from identity/reference repair.

# Acceptance criteria

- The two unrelated tasks no longer share `LIFEOS-1711`.
- The completed ownership-manifest task remains `LIFEOS-1711` and otherwise unchanged.
- The Obsidian plugin CI backlog task has one unique ID and matching filename.
- Repository task validation passes and deterministically rejects duplicate task IDs if such validation is part of the current task contract.

# Documentation impact

Status: required

- `tasks/README.md`: document global repository task-ID uniqueness and the deterministic validation command now enforced by PR fast checks.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: completed task files are durable implementation history and newly discovered independent work is captured as backlog work.
- `tasks/README.md`: task state and dependency metadata are repository workflow contracts.
