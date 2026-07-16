---
id: LIFEOS-004
title: Create the initial registry schema
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-003]
affected_paths:
  - src/lifeos/registry/
  - tests/registry/
risk: medium
---

# Goal

Create an idempotent SQLite schema for file state, source versions, generated outputs, and migrations.

# Scope

- Create migration infrastructure.
- Create `files`, `source_versions`, `generated_outputs`, and `schema_migrations`.
- Record schema version.

# Out of scope

- Task registry
- Proposal tables
- Graph state tables

# Acceptance criteria

1. Fresh initialization succeeds.
2. Repeated initialization is idempotent.
3. Existing rows survive.
4. Tests inspect columns and constraints.

# Validation

```bash
pytest tests/registry/test_schema.py
```

# Relevant decisions

- `DD-002`
- `docs/data-model.md`
