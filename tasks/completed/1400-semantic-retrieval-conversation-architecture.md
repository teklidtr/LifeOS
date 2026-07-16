---
id: LIFEOS-1400
title: Define semantic retrieval and knowledge conversation architecture
status: completed
phase: 14
depends_on:
  - LIFEOS-1311
risk: high
---

# Goal

Audit the completed repository, resolve architectural boundaries, and create the complete Phase 14 task sequence.

# Scope

- Audit ingestion, note schemas, lexical search, Graphify, proposals, bridge, plugin, tests, and user manual.
- Define canonical and derived state, stable provenance, privacy boundaries, provider-neutral seams, failure states, and migration strategy.
- Create `LIFEOS-1401` through `LIFEOS-1411` in repository task format.

# Acceptance criteria

- Architecture does not duplicate exact search, ingestion, Graphify, or proposal responsibilities.
- UI-first, privacy, rebuild, migration, large-vault, and provider-neutral risks are explicitly resolved.
- The implementation sequence has complete dependencies and does not stop at planning.

# Validation commands

```bash
python3 scripts/validate_manual_links.py
git diff --check
```

# Relevant design decisions

- DD-060 through DD-066
