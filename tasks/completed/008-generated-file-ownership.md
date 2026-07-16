---
id: LIFEOS-008
title: Implement generated-file ownership
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-004, LIFEOS-007]
affected_paths:
  - src/lifeos/ownership/
  - tests/ownership/
  - .lifeos.example/generated-ownership.json
risk: medium
---

# Goal

Track which fully generated files belong to which generator.

# Scope

- Define manifest schema.
- Refuse full-file replacement of unowned files.
- Allow an owner generator to update its files.
- Record generator version and output hash.

# Out of scope

- Managed-block editing
- Proposal application
- Index generation

# Acceptance criteria

1. Unowned files are never overwritten.
2. Owned files update safely.
3. Invalid entries are rejected.
4. Collisions are tested.

# Validation

```bash
pytest tests/ownership
```

# Relevant decisions

- `DD-009`
- `DD-012`
- `docs/safety-and-ownership.md`
