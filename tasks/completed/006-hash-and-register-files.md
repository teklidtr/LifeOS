---
id: LIFEOS-006
title: Hash and register vault files
status: ready
milestone: phase-1-deterministic-foundation
depends_on: [LIFEOS-004, LIFEOS-005]
affected_paths:
  - src/lifeos/registry/
  - src/lifeos/scanner/
  - tests/registry/
risk: medium
---

# Goal

Persist file hashes and classify scan results as new, modified, unchanged, or deleted.

# Scope

- Calculate SHA-256.
- Upsert file records.
- Record last-seen timestamps.
- Detect deletions only after successful scans.
- Avoid speculative move detection.

# Out of scope

- Semantic identity matching
- Proposal generation
- Graph updates

# Acceptance criteria

1. All states are tested.
2. No file content is stored.
3. Interrupted scans do not create false deletions.
4. Large files are streamed.

# Validation

```bash
pytest tests/registry/test_file_tracking.py
```

# Relevant decisions

- `DD-002`
- `DD-006`
- `DD-019`
