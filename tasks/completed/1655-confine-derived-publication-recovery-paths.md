---
id: LIFEOS-1655
title: Confine derived publication recovery paths
status: completed
phase: hardening
depends_on:
  - LIFEOS-902
  - LIFEOS-910
risk: critical
---

# Goal

Prevent tampered derived-publication runtime journals from selecting or recursively deleting paths
outside their publication generation directory during inspection or recovery.

# Problem and current behavior

In `src/lifeos/publication.py`, `_read_journal` accepts any nonempty `generation_id`,
checks only the `.staging-` prefix of `staging_name`, and only type-checks
`previous_generation`. `recover_publication` joins journal values beneath
`root / "generations"` and passes the resulting candidates to `shutil.rmtree` during
prepared recovery and staging cleanup. These persisted runtime values are untrusted.

A safe review reproduction used a disposable publication root with a `generations/`
directory, no active pointer, and this `transaction.json`:

```json
{"schema_version":1,"generation_id":"../../victim","staging_name":".staging-safe","previous_generation":null,"phase":"prepared"}
```

With a sibling `victim/` sentinel under the temporary parent, the prepared cleanup
selected that directory outside the publication root for recursive deletion. Regression
tests must use disposable fixtures or an intercepted deletion sink, never a real vault.

The module already has `_validate_generation_name` for active-pointer IDs, but the
journal parser does not use it. Centralize the persisted-component invariant instead
of adding unrelated call-site checks. Preserve safe existing generation identifiers;
do not invent a UUID-only schema. Current staging names are generated as
`.staging-{generation_id[:16]}-{random_suffix}`.

# Scope

- Strictly validate every persisted generation, staging, and previous-generation identifier before
  constructing a filesystem path.
- Resolve recovery candidates beneath the descriptor-pinned publication generations directory and
  reject traversal, absolute paths, separators, symlinks, and unexpected file types.
- Make cleanup operate only on identities proven to belong to the selected publication root.
- Add adversarial recovery tests for relative traversal, absolute paths, crafted staging prefixes,
  symlink replacement, and malformed journal types.
- Audit every consumer of `PublicationJournal`, `_read_journal`, and `recover_publication` for the
  same persisted-path invariant.

# Out of scope

- Replacing the immutable-generation publication design.
- Changing canonical Markdown or capture merge/split transactions.
- Recovering intentionally unsupported or corrupt journal schemas.

# Acceptance criteria

- No journal-controlled value can escape the publication generation directory for read, rename,
  activation, cleanup, or recursive deletion.
- A malicious or malformed runtime journal fails closed without modifying any path outside the
  publication root.
- Validate all three persisted identifiers before path construction. Include absolute paths,
  separators, dot segments, NUL, empty values, wrong JSON types, and crafted `.staging-` traversal
  prefixes. Optional `previous_generation` remains nullable, not an unchecked path escape.
- Directory/symlink identity replacement cannot redirect recovery cleanup outside the pinned
  generation directory; rejection leaves outside sentinel bytes untouched.
- Valid prepared, published, complete, and stale-cleanup recovery behavior remains compatible.
- Existing integrity inventories, active-pointer selection, and supported Linux/macOS behavior
  remain intact. A rejected journal never gains authority to modify canonical content.
- Focused publication, integrity, symlink-race, and full practical validation pass.

# Documentation impact

Status: none
Reason: This closes an implementation-level path-confinement defect without changing the
documented immutable-generation publication or recovery contract.

# Validation

```bash
rtk .venv/bin/pytest -q tests/test_publication.py tests/test_publication_integrity.py
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

Local validation on 2026-09-02:

- Focused publication and integrity suite: 62 passed.
- Ruff, mypy, and diff checks passed.
- The full suite was attempted. Its remaining failures are the pre-existing macOS
  recovery-readiness cases tracked by LIFEOS-1659 (including tests whose
  protected-path assertion mistakes macOS's `/private/var/...` temporary root
  for a vault `private/` scope). The broad suite passed when those already
  tracked cases were deselected; the full suite will be rerun after LIFEOS-1659.
- GitHub review checkpoints could not be requested locally because the `gh`
  executable is unavailable. Security review remains required before merge.

# Relevant decisions

- `AGENTS.md`: filesystem/trust-boundary review, canonical state, and bounded consolidation.
- `docs/architecture.md`: derived state is not canonical authority.
- DD-001: canonical Markdown remains authoritative; derived generations are disposable views.
- DD-013 and DD-033: deterministic indexes and disposable rebuildable query state.
- LIFEOS-902: derived output publishes through immutable generations and one active pointer.
- LIFEOS-910: published generations are verified against an exact integrity inventory.

The completed LIFEOS-902 and LIFEOS-910 tasks describe the publication-specific contract.
DD-052 concerns living replanning, not atomic publication, and is not authority for this task.
Follow `AGENTS.md`'s security-sensitive review requirements before a future merge.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `xhigh`.
- **Reason for the recommendation:** This is a destructive filesystem trust-boundary defect with
  traversal, persisted-state validation, identity-race, and crash-recovery compatibility concerns.
  Strong repository-wide reasoning is warranted even if the final implementation stays compact.
