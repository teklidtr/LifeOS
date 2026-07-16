---
id: LIFEOS-106
title: Deterministic application and rollback
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-105]
risk: high
affected_paths:
  - src/lifeos/proposals/application.py
---

# Goal

Execute explicitly approved proposal patches deterministically, applying filesystem changes securely, and guaranteeing full atomic rollback upon any partial failure.

# Scope

- Receive an approved, structurally validated proposal.
- Execute the preflight validation (LIFEOS-104).
- Create atomic backups of all targets in the same directory before mutation.
- Execute mutations for `replace_managed_block`, `create_generated_file`, `replace_generated_file`, `create_file`, and `patch_human_file`.
- In case of failure (I/O error, missing targets, permission denied):
  - Automatically and atomically restore all previous target bytes from backups.
  - Fail the entire application process safely.
- In case of success:
  - Trigger the lifecycle transition `approved` -> `applied`.
  - Clean up all temporary backup files.

# Out-of-Scope

- Do not implement SQLite index updates here.
- Do not bypass explicit approval (a proposal must be `approved` to be applied).

# Acceptance Criteria

1. Approved proposals mutate their specific target paths deterministically.
2. If any patch in the proposal fails, the vault is returned precisely to its state prior to application using same-directory `os.replace` backups.
3. Successful application leaves no temporary backup files.
4. An applied proposal correctly transitions its state to `applied` in the `proposal.md` frontmatter.

# Validation Commands

```bash
pytest tests/proposals/test_application.py
```

# Relevant Design Decisions

- Proposal application is explicit and deterministic.
- Consequential changes require explicit approval.
- Human-owned content must never be silently overwritten.
