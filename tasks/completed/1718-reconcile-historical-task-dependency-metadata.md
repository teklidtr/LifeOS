---
id: LIFEOS-1718
title: Reconcile historical task dependency metadata
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Make historical task dependency metadata structurally consistent enough for deterministic repository-wide dependency-reference validation without rewriting task history or changing completed task identities.

# Problem and evidence

LIFEOS-1716's first dependency-validation attempt exposed legacy completed-task metadata that predates the current task contract. Examples include task files with no `depends_on` field, non-list legacy shapes, and historical dependency aliases such as `LIFEOS-300`, `LIFEOS-500`, `LIFEOS-116`, and `LIFEOS-1600` that do not resolve to current task IDs.

Those records are historical evidence, so they should not be silently reinterpreted inside the duplicate-ID repair. The repository needs a dedicated reconciliation pass before dependency-reference validation can become an always-on CI invariant.

# Scope

- Inventory historical task files whose `depends_on` metadata is missing, structurally incompatible with the current task contract, or references a non-resolving historical alias.
- Determine the intended historical dependency target from repository evidence where it is unambiguous.
- Normalize only dependency metadata required for deterministic validation while preserving task IDs, completion evidence, scope, acceptance criteria, and historical narrative.
- Add regression coverage for the supported dependency metadata shapes and unresolved-reference failures.
- Extend `scripts/validate_tasks.py` to validate dependency references only after the historical inventory is compatible.

# Out of scope

- Renumbering completed tasks.
- Changing task completion claims or historical implementation evidence.
- Implementing product work referenced by historical tasks.
- Broad task-format migrations unrelated to dependency metadata.

# Required invariants

- Completed task IDs remain immutable.
- Historical dependency meaning is preserved rather than guessed when evidence is ambiguous.
- Every dependency enforced by CI resolves deterministically to the intended task identity.
- Dependency validation does not make legacy-but-valid historical records fail merely because they predate the current formatting convention.

# Acceptance criteria

- The repository has an explicit inventory or deterministic migration for all legacy dependency metadata that would otherwise fail dependency-reference validation.
- All normalized dependency references resolve to repository task IDs or are explicitly documented as intentionally non-enforceable historical metadata.
- `scripts/validate_tasks.py` can validate supported dependency references repository-wide without false failures from known legacy records.
- Regression tests cover missing/legacy shapes, historical aliases, multiline dependencies, and unresolved dependency IDs.
- Repository fast checks pass with dependency validation enabled.

# Documentation impact

Status: required

- `tasks/README.md`: document the supported dependency metadata contract and repository validation behavior once dependency validation is enabled.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- `git diff --check`

# Validation

- Repository inspection corrected the causal diagnosis in the original problem statement: `LIFEOS-300`, `LIFEOS-500`, `LIFEOS-116`, and `LIFEOS-1600` are valid completed task identities on current master. The first dependency-validation attempt produced false unresolved references because legacy dependency parsing could exclude a target task from the identity index; the implementation now indexes task identity independently from dependency metadata parsing.
- The master snapshot at `5503181ce1c02b825da32c7adf3e69f2474cbaf3` contains exactly 14 completed tasks with no `depends_on` field: `LIFEOS-107.1`, `LIFEOS-107.2`, `LIFEOS-107.3`, `LIFEOS-107.4`, `LIFEOS-107.5`, `LIFEOS-107.6`, `LIFEOS-110`, `LIFEOS-116`, `LIFEOS-300`, `LIFEOS-400`, `LIFEOS-500`, `LIFEOS-600`, `LIFEOS-700`, and `LIFEOS-800`. No completed task with an existing `depends_on` field required an opaque or scalar legacy exemption.
- `scripts/validate_tasks.py` records those 14 identities in a closed `_LEGACY_DEPENDENCY_BASELINE`, each grandfathered only for the exact `missing` form. New completed tasks and changed baseline records must use canonical YAML-style task-ID lists; opaque and scalar forms cannot silently bypass CI.
- Regression coverage verifies historical targets with missing dependency metadata remain resolvable, indented empty and multiline lists resolve, malformed dependency metadata does not hide task identity, unresolved IDs fail, active tasks require list metadata, newly completed tasks cannot omit dependency metadata, and an inventoried task fails if its dependency form drifts from the recorded baseline.
- PR #57 `PR checks` run `33956661162` passed on review-fix head `8acb71197568e1100b8be6d9c444437ed6494761`. The `fast-checks` job passed task workflow validation, documentation impact, manual links, Ruff, mypy, compilation, full test collection, and the project contract tests; the independent `obsidian-plugin` job also passed.
- A pre-review `Full validation` run `33955968317` passed on implementation head `00f64ffad1225c557b317aad5e82bbd663bdf9fb`, including full pytest shards and Docker/setup validation. Because later review-fix and completion commits changed the head, repository workflow requires a fresh final full-validation checkpoint before merge.
- The first Codex review against `00f64ffad1` raised two findings. The ready-transition finding was a diff-view false positive: commit `59fdec1f480379462704269af3773ba4e5b97105` promoted LIFEOS-1718 to `ready` before child commit `4650934785caf05c5a04baa0e401a6304e6776ae` moved it to `in-progress`. The valid legacy-exemption finding was fixed in `8acb71197568e1100b8be6d9c444437ed6494761` with the closed exact-form baseline and regression coverage. Both threads were resolved.
- Codex re-review completed against `8acb711975` and reported no major issues.
- A local checkout remained unavailable because the execution environment could not resolve `github.com`. Per `AGENTS.md`, unavailable local execution is not represented as a pass. The exact local `git diff --check` command therefore remained unavailable; GitHub diff inspection and repository CI supplied the practical static/executable validation layers.
- `docs/user-manual/` was reviewed for impact. This task changes repository-maintainer workflow validation only, not user-visible LifeOS behavior or product architecture; the required current contract is documented in `tasks/README.md`.
- Security review was intentionally skipped per the user's explicit instruction.
- No newly discovered independent implementation work required a separate backlog task.
- This completion move changes the task path/status after the validated review-fix head. Fresh current-head PR checks and the final `full-validation` checkpoint are required before merge.

# Relevant decisions

- `AGENTS.md`: completed task files are historical evidence; newly discovered independent work belongs in backlog rather than expanding the current PR.
- `tasks/README.md`: task dependency metadata participates in task eligibility and repository workflow.
