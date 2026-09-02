---
id: LIFEOS-001
title: Verify the project skeleton
status: completed
milestone: phase-0-project-skeleton
depends_on: []
affected_paths:
  - README.md
  - AGENTS.md
  - docs/
  - tasks/
  - src/
  - tests/
risk: low
---

# Goal

Create an automated test that verifies the required repository structure and core documents exist.

# Scope

- Define required root files and directories.
- Add a test with clear missing-entry errors.

# Out of scope

- Vault scanning
- Registry implementation
- Runtime `.lifeos/` creation

# Acceptance criteria

1. The test passes on the bootstrap repository.
2. Removing a required file makes it fail clearly.
3. No runtime directories are created.

# Validation

```bash
pytest tests/project/test_skeleton.py
```

# Relevant decisions

- `docs/implementation-strategy.md`
- `docs/roadmap.md#phase-0-project-skeleton`
