---
id: LIFEOS-102
title: Typed patch schema and canonical serialization
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-101]
risk: medium
affected_paths:
  - src/lifeos/proposals/patches.py
---

# Goal

Define a typed JSON schema as the canonical patch representation, enabling precise, deterministic patches without relying solely on brittle unified diffs.

# Scope

- Implement Python data models for the defined explicit operations:
  - `replace_managed_block`
  - `create_generated_file`
  - `replace_generated_file`
  - `create_file`
  - `patch_human_file`
- Each operation must record:
  - operation type
  - target vault-relative path
  - target/base hash
  - operation-specific preconditions
  - operation-specific payload
- Implement canonical JSON serialization and deserialization for these operations.

# Out-of-Scope

- Do not implement the actual execution of these patches against the filesystem.
- Do not implement preflight validation of target-hashes against the live registry.
- Do not implement the CLI command to apply patches.

# Acceptance Criteria

1. Typed operations are modeled correctly in Python.
2. Serialization to JSON produces a deterministic output format.
3. Deserialization from JSON reproduces identical typed operations.
4. A `patch_human_file` operation supports a payload containing a unified diff, but it is encapsulated within the JSON schema rather than being a raw `.patch` file on disk.

# Validation Commands

```bash
pytest tests/proposals/test_patches.py
```

# Relevant Design Decisions

- Use typed JSON as the canonical patch representation.
- Ensure standard structural fields (operation, target path, base hash) exist across all operations.
