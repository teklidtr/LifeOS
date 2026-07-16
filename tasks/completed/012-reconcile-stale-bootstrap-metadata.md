---
id: LIFEOS-012
title: Reconcile stale bootstrap metadata
status: completed
milestone: phase-0-project-skeleton
depends_on: []
affected_paths:
  - FILE_INDEX.txt
risk: low
---

# Goal

Make bootstrap inventory and backlog metadata reflect the repository's current state.

# Historical Note

The duplicate LIFEOS-011 metadata and the already-satisfied RTK-ignore task
were reconciled in commit b83d00c.

# Scope

- remove obsolete `FILE_INDEX.txt`
- correct the stale LIFEOS-116 heading
- verify task identifiers and repository metadata match the current tree

# Out of scope

- Registry implementation
- Vault indexing or generated vault indexes
- Changes to RTK configuration or local RTK data

# Acceptance criteria

1. The repository has no obsolete `FILE_INDEX.txt`.
2. LIFEOS-116 and LIFEOS-011 have unique frontmatter identifiers.
3. The codebase has a clean working tree matching metadata expectations.

# Validation

```bash
git status --short
git grep -n "FILE_INDEX.txt"
git grep -n '^id: LIFEOS-011$' tasks
git grep -n '^id: LIFEOS-116$' tasks
```

# Relevant decisions

- `DD-013`
- `docs/roadmap.md#phase-0-project-skeleton`

**Implementation completed.**
* implementation commit hash: e108a137b90d25d225bdd65d7f53481067e4b39c
* obsolete `FILE_INDEX.txt` removed
* LIFEOS-116 heading corrected
* LIFEOS-011 and LIFEOS-116 frontmatter IDs are unique
* no production-code change was required
