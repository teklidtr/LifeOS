---
id: LIFEOS-003
title: Define the configuration model
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-002]
affected_paths:
  - src/lifeos/config/
  - tests/config/
  - .lifeos.example/config.yml
risk: low
---

# Goal

Define and load the minimum deterministic configuration needed to locate a vault and runtime directory.

# Scope

- Support vault root.
- Default runtime directory to `.lifeos/`.
- Support Graphify and export enablement flags.
- Validate without creating paths.

# Out of scope

- Secrets
- Provider configuration
- Domain-specific folder rules

# Acceptance criteria

1. Valid configuration loads.
2. Defaults are deterministic.
3. Invalid YAML and missing roots are tested.
4. Unknown-key behavior is documented.

# Validation

```bash
pytest tests/config
```

# Relevant decisions

- `DD-001`
- `DD-018`
- `DD-029`
