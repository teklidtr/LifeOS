---
id: LIFEOS-009
title: Create basic structural lint
status: completed
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-005, LIFEOS-007, LIFEOS-008]
affected_paths:
  - src/lifeos/lint/
  - tests/lint/
risk: medium
---

# Goal

Create deterministic lint checks for foundational vault structure.

# Scope

- Check invalid YAML.
- Check duplicate stable IDs.
- Check managed-block errors.
- Check invalid statuses and confidence.
- Check ownership conflicts.
- Support error, warning, suggestion.

# Out of scope

- Semantic contradictions
- Unsupported claims
- Personal-pattern review

# Acceptance criteria

1. Findings are stable and machine-readable.
2. Each includes path, code, severity, and message.
3. Multiple findings are supported.
4. Lint never mutates.

# Validation

```bash
pytest tests/lint
```

# Relevant decisions

- `DD-005`
- `DD-009`
- `DD-012`
- `DD-015`
