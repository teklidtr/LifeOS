---
id: LIFEOS-1507
title: Add experiment migration privacy and recovery
status: completed
phase: 15
depends_on:
  - LIFEOS-1506
risk: high
---

# Goal

Complete conservative legacy migration, protected-scope privacy controls, interrupted rebuild recovery, bounded performance behavior, and deterministic evaluation fixtures.

# Implemented

- Added legacy experiment migration preview and application with stable source hashes, deterministic identities, preserved source files, resumable audit state, conflict detection, and no duplicate migration.
- Added a bounded provider-context preview that discloses every included path, excludes protected roots by default, follows no linked sensitive notes automatically, supports explicit root permission and redaction, and keeps deterministic analysis local.
- Added recovery diagnostics for malformed and duplicate artifacts, moved and deleted identities, missing linked sources, orphaned observation notes, interrupted rebuilds, and disposable index recreation.
- Added strict bridge capabilities and Obsidian workspace actions for migration, privacy disclosure, and recovery.
- Added deterministic fixtures for source changes, interruption and resume, protected scopes, redaction, moves, duplicates, orphans, deleted runtime state, and 60-artifact history rebuilds.

# Required invariants verified

- Original legacy files remain unchanged.
- Migration fails closed when a source changes after preview.
- Sensitive information is not included merely because it is linked.
- Runtime indexes and migration checkpoints remain disposable or resumable.
- Canonical Markdown remains usable without the plugin.

# Validation

- `PYTHONPATH=src pytest -q tests/experiments/test_migration_privacy_recovery.py tests/bridge/test_experiment_bridge.py`: 9 passed.
- `cd packages/obsidian-plugin && npm run typecheck`: passed.
- `cd packages/obsidian-plugin && npm test`: 39 passed.
- `cd packages/obsidian-plugin && npm run build`: passed.
- `git diff --check`: passed.
