---
id: LIFEOS-105
title: Approval and lifecycle transitions
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-104]
risk: low
affected_paths:
  - src/lifeos/proposals/lifecycle.py
---

# Goal

Implement explicit, durable lifecycle transitions for proposals, allowing humans to securely approve, reject, or mark proposals as stale, persisting these decisions in `proposal.md`.

# Scope

- Implement transition functions that safely mutate the `status` field in `proposal.md` frontmatter.
- Support transitions: `draft` -> `pending`, `pending` -> `approved` / `rejected`, `approved` -> `applied` / `stale`.
- Record durable human decisions, such as approval/rejection timestamps and the approving identity, in the `proposal.md` frontmatter.
- Enforce valid state transitions (e.g., an applied proposal cannot become pending).

# Out-of-Scope

- Do not implement SQLite synchronization here (handled in LIFEOS-107).
- Do not apply patches.

# Acceptance Criteria

1. Transitions mutate the `proposal.md` frontmatter accurately and durably.
2. The proposal directory structure is unaffected; no files are moved.
3. Invalid state transitions (e.g., `applied` -> `pending`) are rejected.
4. Timestamps for approval and rejection are successfully captured in the frontmatter.

# Validation Commands

```bash
pytest tests/proposals/test_lifecycle.py
```

# Relevant Design Decisions

- Durable human decisions such as approval, rejection, and application timestamps belong in `proposal.md`.
- Proposals are never moved into state-specific folders.
