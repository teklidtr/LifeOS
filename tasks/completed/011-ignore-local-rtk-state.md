---
id: LIFEOS-011
title: Ignore local RTK state
status: completed
milestone: phase-0-project-skeleton
depends_on: []
affected_paths:
  - .gitignore
risk: low
---

# Goal

Keep repository-local RTK runtime metadata from appearing as untracked project work.

# Scope

- Confirm that `.tokensave/` contains only local RTK runtime state.
- Add a narrowly scoped ignore rule for `.tokensave/`.
- Verify that the local files remain present but no longer appear in Git status.

# Out of scope

- Deleting local RTK state
- Installing or configuring RTK
- Changing CLI behavior

# Acceptance criteria

1. Files under `.tokensave/` are ignored by Git.
2. No tracked project files or broader path patterns are ignored.
3. Existing local RTK state is not deleted.

# Validation

```bash
git check-ignore -v .tokensave/tokensave.db
git status --short
```

# Relevant decisions

- `docs/roadmap.md#phase-0-project-skeleton`

**Implementation completed.**
* `.tokensave/` is present in the committed `.gitignore`
* `git check-ignore` confirms local RTK state is ignored
* no production-code change was required
