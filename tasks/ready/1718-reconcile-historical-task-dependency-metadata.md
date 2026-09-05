---
id: LIFEOS-1718
title: Reconcile historical task dependency metadata
status: ready
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

# Relevant decisions

- `AGENTS.md`: completed task files are historical evidence; newly discovered independent work belongs in backlog rather than expanding the current PR.
- `tasks/README.md`: task dependency metadata participates in task eligibility and repository workflow.
