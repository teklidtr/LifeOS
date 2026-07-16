---
id: LIFEOS-005
title: Scan supported vault files
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-003, LIFEOS-004]
affected_paths:
  - src/lifeos/scanner/
  - tests/scanner/
risk: medium
---

# Goal

Scan the configured vault deterministically without mutating it.

# Scope

- Discover Markdown and common attachments.
- Ignore runtime, VCS, and transient Obsidian paths.
- Return normalized vault-relative paths.
- Sort deterministically.

# Out of scope

- Content parsing
- Hash persistence
- Stable IDs

# Acceptance criteria

1. Repeated scans have identical order.
2. Ignored paths are excluded.
3. Paths never escape the vault.
4. Symlinks and nesting are tested.

# Validation

```bash
pytest tests/scanner
```

# Relevant decisions

- `DD-001`
- `DD-002`
