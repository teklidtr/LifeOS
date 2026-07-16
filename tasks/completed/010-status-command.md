---
id: LIFEOS-010
title: Implement `lifeos status`
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-006, LIFEOS-009]
affected_paths:
  - src/lifeos/cli.py
  - src/lifeos/status/
  - tests/status/
risk: low
---

# Goal

Expose a concise read-only summary of vault and registry state.

# Scope

- Show file counts by state.
- Show lint counts.
- Show registry version.
- Show Graphify/export enablement.
- Support human and JSON output.

# Out of scope

- Proposal state
- Daily planning
- Graph synchronization

# Acceptance criteria

1. Output is deterministic.
2. JSON has a documented schema.
3. The command never mutates.
4. Empty and populated fixtures are tested.

# Validation

```bash
pytest tests/status
lifeos status --help
```

# Relevant decisions

- `DD-002`
- `docs/roadmap.md#phase-1-deterministic-foundation`
