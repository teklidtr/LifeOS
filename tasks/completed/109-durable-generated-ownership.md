---
id: LIFEOS-109
title: Make generated ownership durable
status: completed
milestone: phase-2-proposal-engine
depends_on: []
risk: medium
affected_paths:
  - src/lifeos/ownership/__init__.py
  - src/lifeos/ownership/manifest.py
  - system/generated-ownership.json
  - docs/design-decisions.md
  - docs/safety-and-ownership.md
  - tests/ownership/test_manifest.py
---

# Goal

Move generated-file ownership from potentially disposable `.lifeos/` state to a canonical Git-tracked vault record at `system/generated-ownership.json`.

# Scope

- Define `DEFAULT_OWNERSHIP_MANIFEST_PATH` in `src/lifeos/ownership/manifest.py` and re-export it in `__init__.py`.
- Extract the existing serialization logic from `_save_manifest` into a pure helper `serialize_generated_ownership_bytes`.
- Create the empty manifest `system/generated-ownership.json` using the pure helper to ensure exact byte match with runtime behavior.
- Document the new architecture decision: generated ownership is durable authorization data.
- Remove `.lifeos.example/generated-ownership.json`.
- Preserve existing missing-manifest fallback behavior in `GeneratedOwnership.load(...)` to avoid breaking existing lint or task 008 behavior.
- Add focused tests verifying path properties, loading, and serialization.

# Out-of-Scope

- Do not implement proposal preflight, target hashing, managed-block checks, or patch application.
- Do not inspect Git or `.gitignore` at runtime.
