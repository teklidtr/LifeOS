---
id: LIFEOS-111
title: Patch schema v2 for generator version provenance
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-105]
---

# Goal

Provide canonical generator version provenance for generated files by introducing Patch Schema Version 2.

# Context

LIFEOS-106 (Application and Rollback) requires recording `generator_version` into the `system/generated-ownership.json` manifest when `create_generated_file` and `replace_generated_file` patches are applied. Currently, Patch Schema Version 1 lacks an authoritative source for the new generator version.

# Scope

- Introduce `schema_version: 2` for `PatchDocument`.
- Update `create_generated_file` to include `generator_version`.
- Update `replace_generated_file` to include `generator_id` (the new identity) and `generator_version` (the new version), alongside `expected_generator_id` (for the pre-mutation check).
- Ensure legacy `schema_version: 1` documents retain their existing semantics without silent breakage.
- Ensure loading and preflight correctly handle the new schema version.
