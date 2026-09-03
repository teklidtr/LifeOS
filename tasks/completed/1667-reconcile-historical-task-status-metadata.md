---
id: LIFEOS-1667
title: Reconcile historical task status metadata
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Make historical task frontmatter agree with the existing task-state directories without
rewriting completion evidence, changing IDs, or claiming unresolved product defects are fixed.

# Problem and current behavior

The 2026-09-02 review-handoff inventory found 32 task files under `tasks/completed/`
whose frontmatter still says `ready` or `backlog`. Before this task was added, the
inventory contained 191 completed-directory files and 11 backlog files; no ready or
in-progress task files existed. The new/enriched review backlog files were consistent.

The mismatches are:

- `status: ready`: LIFEOS-001 through LIFEOS-010, LIFEOS-101 through LIFEOS-105,
  LIFEOS-109, and LIFEOS-1000 (17 files).
- `status: backlog`: LIFEOS-100, LIFEOS-115, LIFEOS-207, and LIFEOS-1001 through
  LIFEOS-1012 (15 files).

Concrete examples are `tasks/completed/007-parse-durable-note-metadata.md`,
`tasks/completed/109-durable-generated-ownership.md`, and
`tasks/completed/1002-local-desktop-bridge.md`. These files are dependencies of the
new parser, ownership-status, and bridge-cancellation follow-ups, respectively.
Directory-based workflow inspection and frontmatter-based tooling therefore disagree
about historical task state.

`tasks/README.md` explicitly requires frontmatter status to match the destination
directory, and `AGENTS.md` requires `completed` on completion. Neither document exempts
historical tasks. The statement that a completed task is historical evidence does not
make contradictory state metadata authoritative or allow rewriting that evidence.

# Scope

- Re-inventory task directories and inspect historical placement/completion evidence
  for the listed mismatches; confirm that this is stale metadata, not active work
  accidentally placed in the completed directory.
- Correct only contradictory frontmatter status values to match their verified
  existing state directories. Keep filenames, IDs, dependencies, task bodies, acceptance
  criteria, and historical validation/results unchanged.
- Check all state directories afterward so another stale metadata value is not missed.
  Respect any actual task-state changes made since the review instead of blindly applying
  the historical list.

# Out of scope

- Reopening or moving historical tasks automatically.
- Retroactive task-template modernization, new CI machinery, or rewriting task bodies.
- Repairing the still-open product defects recorded in LIFEOS-1655, LIFEOS-1656, or
  LIFEOS-1658 through LIFEOS-1666; their backlog state remains unchanged by this task.
- Claiming old acceptance criteria/tests have just passed or changing production code.

# Acceptance criteria

- Every task file's frontmatter state agrees with its verified directory state.
- The 32 reviewed mismatches are reconciled or any genuinely ambiguous placement is
  documented and resolved explicitly rather than guessed.
- Stable IDs, filenames, dependencies, historical bodies, and completion evidence retain
  their existing content. Only status fields and this task's normal workflow/evidence
  updates change.
- No other task is promoted, implemented, or falsely declared fixed by this cleanup.
- A final read-only inventory proves state consistency and unique IDs, and a diff review
  confirms that no source, tests, or unrelated documentation changed.

# Documentation impact

Status: none
Reason: This corrects historical task metadata to the already documented directory-based
workflow. It does not change that workflow, user behavior, architecture, or historical
implementation/validation claims.

# Validation

```bash
rtk proxy rg -n '^id:|^status:' tasks/backlog tasks/ready tasks/in-progress tasks/completed
rtk git diff --word-diff=plain -- tasks
rtk git diff --check
```

Use a read-only YAML inventory to assert each task's `status` equals its parent state
directory and every `id` is unique. Exclude directory README files, preserve historical
decimal/alphanumeric IDs, and check all four task states rather than only the diff.
No behavioral pytest run is required for status-field-only changes.

# Relevant decisions

- `AGENTS.md`: implementation workflow, task completion updates, and preservation of
  historical evidence and unrelated files.
- `tasks/README.md`: state directories, matching frontmatter, and dependency eligibility.
- No new product architecture or design decision is introduced; the repository workflow
  itself is the applicable authority.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `low`.
- **Reason for the recommendation:** This is a deterministic, status-field-only correction
  with a known mismatch inventory and clear directory-based checks. It requires neither
  production debugging nor new architectural or semantic decisions.

# Validation results

- The pre-change read-only GitHub inventory reproduced the recorded mismatch set exactly:
  17 completed-directory files with `status: ready` and 15 with `status: backlog`.
- The final comparison against master after reconciliation shows those 32 historical task
  files changed by exactly one removed line and one added line each. No source, test,
  architecture, user-manual, or unrelated documentation file changed.
- Stable IDs, filenames, dependencies, and historical task bodies were preserved. The diff
  contains no historical ID/dependency edits or historical task moves; one accidental final
  newline change in LIFEOS-109 was detected during diff review and restored before completion.
- A local checkout could not be acquired in the execution environment because GitHub DNS
  resolution failed (`Temporary failure in name resolution` / `Could not resolve host`).
  Therefore the listed `rtk` commands and the standalone local YAML inventory could not be
  executed here. The closest available static validation used the complete pre-change mismatch
  inventory, direct branch reads, and GitHub's master-to-branch comparison. Because this task
  neither adds nor edits any task ID, it cannot introduce a duplicate ID relative to the audited
  base; PR CI remains the independent repository check.
- No behavioral pytest run was performed, as the task explicitly does not require one for
  status-field-only changes.
