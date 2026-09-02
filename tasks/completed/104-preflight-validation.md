---
id: LIFEOS-104
title: Target-hash, managed-block, and ownership preflight
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-103, LIFEOS-109]
risk: high
affected_paths:
  - src/lifeos/proposals/validation.py
---

# Goal

Implement robust validation of proposals against the live vault, ensuring target hashes match, managed-block boundaries are respected, and ownership invariants are not violated.

# Scope

- Validate that target files exist (unless it's a creation patch) and their current hashes match the `base_hash` in the proposal.
- For `replace_managed_block` operations, parse the target Markdown file and confirm the named managed block exists and boundaries are intact.
- For generated-file operations (`create_generated_file`, `replace_generated_file`), confirm the operation does not conflict with human-owned files or ownership invariants in `ownership.json`.
- Implement a validator function that takes a loaded proposal and emits a deterministic `validation.json` record of passes/failures.
- Mark proposals whose targets have changed as `stale` (preventing application).

# Out-of-Scope

- Do not implement approval transitions (approval does not bypass this validation).
- Do not apply the patches.

# Acceptance Criteria

1. Target-hash mismatch causes immediate validation failure.
2. Patching a non-existent or malformed managed block causes failure.
3. Modifying a generated file without the correct generator identity causes failure.
4. An explicit validation record can be derived and stored under `.lifeos/proposal-validation/`.
5. An approved proposal whose targets changed is refused as stale.

# Validation Commands

```bash
pytest tests/proposals/test_validation.py
```

# Relevant Design Decisions

- `validation.json` is derived and should normally live under `.lifeos/proposal-validation/`, not as canonical proposal history.
- Approval does not bypass application-time validation. An approved proposal whose targets changed must be refused as stale.
