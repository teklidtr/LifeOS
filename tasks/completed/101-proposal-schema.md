---
id: LIFEOS-101
title: Proposal schema, stable IDs, lifecycle, and tracked layout
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-100]
risk: low
affected_paths:
  - src/lifeos/proposals/schema.py
---

# Goal

Establish the physical Git-tracked storage layout and schema for LifeOS proposals, ensuring proposals are authoritative and their lifecycle state is deterministically stored as frontmatter in `proposal.md`.

# Scope

- Define the on-disk storage layout for proposals: `proposals/<proposal-id>/proposal.md` and `patches.json`.
- Define a stable ID generation mechanism for new proposals.
- Define the `proposal.md` frontmatter schema, particularly the `status` lifecycle field (e.g., draft, pending, approved, rejected, applied, stale).
- Define Python data classes representing the Proposal metadata and lifecycle state.
- Create utility functions to generate a new proposal stub on disk.

# Out-of-Scope

- Do not implement SQLite indexing.
- Do not implement patch schemas or patch serialization.
- Do not move proposal directories to track state (state is strictly metadata).
- Do not implement the actual proposal application or validation.

# Acceptance Criteria

1. Python models can represent a proposal's metadata and lifecycle state.
2. A utility function successfully creates a new `proposals/<proposal-id>/` directory containing a stub `proposal.md` with correct frontmatter and an empty `patches.json`.
3. Proposal status changes are represented strictly as frontmatter mutation in `proposal.md`, without renaming or moving the parent directory.
4. Generated IDs are deterministic, stable, and unique.

# Validation Commands

```bash
pytest tests/proposals/test_schema.py
```

# Relevant Design Decisions

- Proposals live in a Git-tracked top-level `proposals/` directory.
- Lifecycle state is authoritative frontmatter in `proposal.md`. Folders are not moved between pending, approved, etc.
- `validation.json` is derived and should normally live under `.lifeos/proposal-validation/`, not in the main proposal structure.
