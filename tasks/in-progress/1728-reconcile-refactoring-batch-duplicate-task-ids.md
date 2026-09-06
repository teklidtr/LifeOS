---
id: LIFEOS-1728
title: Reconcile duplicate task IDs in the refactoring backlog batch
status: in-progress
phase: hardening
depends_on: []
risk: low
---

# Goal

Restore the repository-wide unique task-ID invariant after the refactoring backlog batch reused completed IDs `LIFEOS-1719` through `LIFEOS-1723`.

# Problem evidence

PR validation for LIFEOS-1727 on master `8cb19c93a4bfe63f2258d126964e364cbfbcb297` fails immediately in `python scripts/validate_tasks.py` because these active backlog tasks reuse completed historical IDs:

- `tasks/backlog/1719-collapse-recovery-readiness-runtime-patching.md` conflicts with completed `LIFEOS-1719`.
- `tasks/backlog/1720-centralize-proposal-document-publication.md` conflicts with completed `LIFEOS-1720`.
- `tasks/backlog/1721-migrate-remaining-proposal-document-publishers.md` conflicts with completed `LIFEOS-1721`.
- `tasks/backlog/1722-make-ingestion-composition-and-provenance-explicit.md` conflicts with completed `LIFEOS-1722`.
- `tasks/backlog/1723-consolidate-mcp-input-and-read-output-contracts.md` conflicts with completed `LIFEOS-1723`.

The validator stops before ordinary fast checks, so unrelated implementation PRs cannot satisfy the required green `fast-checks` gate while this baseline remains.

# Scope

- Assign fresh globally unique `LIFEOS-*` IDs to the five conflicting active backlog tasks.
- Rename their task filenames consistently when repository convention requires it.
- Update dependency references among active tasks so the intended dependency graph is preserved under the new IDs.
- Search all active task metadata for references to the old reused identities and update only references that target these refactoring tasks rather than the completed historical tasks.
- Keep completed task history unchanged.

# Out of scope

- Changing the implementation scope, acceptance criteria, priority, or sequencing of the refactoring tasks beyond identity/reference reconciliation.
- Rewriting completed task history or weakening `scripts/validate_tasks.py` uniqueness enforcement.
- Implementing any of the refactoring tasks themselves.

# Acceptance criteria

- [ ] Every task ID is globally unique across backlog, ready, in-progress, and completed history.
- [ ] The five refactoring tasks use fresh IDs without altering their implementation contracts.
- [ ] Active dependency references still resolve to the intended refactoring tasks.
- [ ] Completed historical task IDs and contents remain unchanged.
- [ ] `python scripts/validate_tasks.py` passes.

# Documentation impact

Status: none
Reason: This reconciles task-planning metadata only; it does not change user-visible behavior, architecture, runtime contracts, setup, or operations.

# Validation

```bash
python scripts/validate_tasks.py
```

Also search the repository for every old and newly assigned task ID to verify references resolve to the intended task identity.

# Relevant design decisions

- `tasks/README.md`: task IDs are globally unique and completed IDs must never be reused.
- Root `AGENTS.md`: newly discovered independent work is recorded as a separate backlog task rather than widening the active implementation task.
