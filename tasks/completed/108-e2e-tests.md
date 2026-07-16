---
id: LIFEOS-108
title: End-to-end workflow tests
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-107]
risk: low
affected_paths:
  - tests/e2e/test_proposals.py
---

# Goal

Verify the complete integration of the proposal engine from creation, loading, validation, approval, index scanning, to final application and rollback.

# Scope

- Write robust integration tests covering the complete lifecycle loop.
- Test a happy path: propose a managed-block change, check status (pending), approve it, check status (approved), apply it, verify the vault file mutated correctly, and check status (applied).
- Test the stale failure path: propose a change, manually alter the target file in the vault, approve the proposal, attempt to apply, verify it is blocked due to hash mismatch (stale), and verify target is untouched.
- Test the partial rollback path: propose two file creations where the second fails (e.g., due to permission error mock), attempt application, verify the first file was rolled back from its backup, and the proposal remains unapplied.

# Out-of-Scope

- Do not implement any new Python application features; this task is strictly validation.

# Acceptance Criteria

1. End-to-end tests pass seamlessly against the completed Phase 2 subsystems.
2. Stale target hashes correctly intercept application even when the proposal is marked approved.
3. Rollbacks prove complete file recovery during a multi-patch failure.

# Validation Commands

```bash
pytest tests/e2e/test_proposals.py
```

# Relevant Design Decisions

- Consequential changes require explicit approval.
- Proposal application must be deterministic and validate target hashes.


# Evidence

- implementation commit: `68c642e`
- focused validation: `3 passed`
- full repository validation: `821 passed, 1 warning`
- Ruff: passed for `src` and `tests/e2e/test_proposals.py`
- mypy: passed for `src`
- happy path covers draft, pending, approved, applied, indexing, and managed-block mutation
- stale approved proposal is blocked without changing the externally modified target
- second-target publication failure rolls back the first creation and leaves the proposal approved
- no production application code changed
