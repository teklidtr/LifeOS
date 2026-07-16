---
id: LIFEOS-002
title: Create the CLI shell
status: ready
milestone: phase-0-project-skeleton
depends_on: [LIFEOS-001]
affected_paths:
  - src/lifeos/cli.py
  - src/lifeos/__init__.py
  - tests/cli/
risk: low
---

# Goal

Create a minimal `lifeos` CLI with help and version output.

# Scope

- Implement `lifeos --help`.
- Implement `lifeos --version`.
- Return non-zero for unknown commands.

# Out of scope

- Vault scanning
- Registry initialization
- Configuration loading

# Acceptance criteria

1. Help states the application purpose.
2. Version matches the package version.
3. Tests cover help, version, and invalid commands.

# Validation

```bash
pytest tests/cli
python -m lifeos.cli --help
```

# Relevant decisions

- `docs/roadmap.md#phase-0-project-skeleton`
