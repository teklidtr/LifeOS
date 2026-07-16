---
id: LIFEOS-007
title: Parse durable note metadata
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-005]
affected_paths:
  - src/lifeos/markdown/
  - tests/markdown/
risk: medium
---

# Goal

Parse YAML frontmatter and managed markers without semantic interpretation.

# Scope

- Extract known durable fields.
- Preserve unknown keys.
- Detect unmatched or nested managed blocks.
- Report line-aware parse errors.

# Out of scope

- Semantic validation
- Automatic repair
- Relationship inference

# Acceptance criteria

1. Invalid YAML does not crash scans.
2. Unknown fields survive.
3. Managed-block errors include path and line.
4. Notes without frontmatter are supported.

# Validation

```bash
pytest tests/markdown
```

# Relevant decisions

- `DD-005`
- `DD-008`
- `DD-009`
