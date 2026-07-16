---
id: LIFEOS-110
status: completed
milestone: proposal-engine
requires: [LIFEOS-105]
---

# LIFEOS-110: Legacy Lifecycle Migration

## Goal
Upgrade legacy proposal documents whose `lifecycle_schema_version` is `null` to the complete `lifecycle_schema_version: 1` contract without changing proposal status, body, patches, or proposal identity.

## Scope
- Analyze every valid proposal under `vault_root/proposals/`.
- Produce deterministic migration plans for legacy proposals.
- Preserve known legacy timestamps and actors.
- Fill missing lifecycle actors with the synthetic actor `legacy`.
- Use `created_at` as the deterministic synthetic submission timestamp.
- Compute the canonical current `review_digest` for every non-draft legacy proposal.
- Supply a deterministic rejection reason when a legacy rejected proposal has none.
- Persist each `proposal.md` through the existing locked atomic transition primitive.
- Provide a CLI command with dry-run support.
- Leave lifecycle-version-1 proposals unchanged.

## Status mapping
- `draft`: set `lifecycle_schema_version: 1`; keep all transition fields null.
- `pending`: synthesize submission fields and current review digest.
- `approved`: synthesize submission fields and digest; preserve approval timestamp; preserve approval actor or use `legacy`.
- `rejected`: synthesize submission fields and digest; preserve rejection timestamp; preserve rejection actor or use `legacy`; preserve approval history when present; synthesize a rejection reason only when absent.
- `applied`: synthesize submission fields and digest; preserve approval and application timestamps; preserve actors or use `legacy`.

## Out of scope
- Changing proposal status.
- Rewriting `patches.json` or proposal body text.
- Updating canonical target files.
- Automatically rebuilding the SQLite registry.
- Inventing missing status timestamps other than submission time.
- Migrating malformed or unloadable proposal directories.

## Acceptance criteria
1. Migration is deterministic and idempotent.
2. A scan containing any error finding performs no writes.
3. Dry-run performs no writes and reports the same migration candidates.
4. All five proposal statuses migrate to metadata accepted by `validate_metadata`.
5. Non-draft migrated proposals have a canonical digest matching current proposal content and patches.
6. Existing status timestamps, non-null decision actors, rejection reasons, extensions, body text, and patch bytes are preserved; legacy submission fields are replaced by the deterministic synthetic submission.
7. Concurrent changes are rejected by the existing proposal transition lock and source-hash checks.
8. Persistence uses `atomic_write_file_secure` through the lifecycle transition service.
9. CLI output reports migrated, skipped, and warning counts and returns nonzero on migration errors.
10. Full tests, Ruff, mypy, and `git diff --check` pass.

## Validation
```bash
uv run pytest tests/proposals/test_migration.py -q
uv run pytest tests/cli/test_migration_cli.py -q
uv run pytest -q
uv run ruff check src/lifeos/cli.py src/lifeos/proposals tests/cli/test_migration_cli.py tests/proposals/test_migration.py
uv run mypy src
git diff --check
```

## Relevant decisions
- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-031: Git-tracked proposals and stable layout
- DD-033: SQLite is disposable and rebuildable
- DD-034: Approval does not bypass current-content validation
