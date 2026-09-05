---
id: LIFEOS-1716
title: Reconcile the duplicate LIFEOS-1711 task ID
status: completed
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

# Validation

- Focused local validation after the final scalar/traversal consolidation: `python -m compileall -q scripts tests` and `pytest -q tests/project/test_task_workflow.py` passed with 8 tests.
- The exact `git diff --check` command passed in a synthetic local git repository containing the branch's changed files. This is stricter than the master diff for whitespace because every reconstructed file line is treated as added.
- Current implementation-head PR `fast-checks` run `33939984855` passed on `c01c31f2186b3f7f1618c436df10f4e56f99f3f9`, including task workflow validation, documentation impact, Ruff, mypy, compilation, collection, and `pytest -q tests/project`.
- A full local checkout remained unavailable because the execution environment could not resolve `github.com`; the isolated behavioral suite and GitHub CI were used as the closest deterministic substitutes in accordance with `AGENTS.md`.
- Normal Codex review found three P2 variants in the new validator: YAML comments could disguise task IDs, nested task files could escape traversal, and YAML comments in `status` could create false failures. All were addressed in the shared scalar/traversal enforcement boundary, covered by regressions, and all review threads are resolved.
- A third mechanical Codex review was intentionally not requested after two consecutive rounds found variants of the same validator invariant; `AGENTS.md` directs consolidation and invariant audit instead of an open-ended review loop. The final diff was audited for parallel scalar parsing and non-recursive task traversal paths.
- Security review was intentionally skipped per the user's explicit instruction.
- Historical `depends_on` incompatibilities discovered by the first validator attempt are independent work and are captured as backlog task `LIFEOS-1718` rather than expanding this PR.
- This completion move changes task path/status after the implementation validations above. Repository workflow therefore requires fresh current-head `fast-checks` and the final `full-validation` checkpoint before merge.

# Relevant decisions

- `AGENTS.md`: completed task files are durable implementation history and newly discovered independent work is captured as backlog work.
- `tasks/README.md`: task state and dependency metadata are repository workflow contracts.
