---
id: LIFEOS-1655
title: Confine derived publication recovery paths
status: backlog
phase: hardening
depends_on:
  - LIFEOS-902
  - LIFEOS-910
risk: critical
---

# Goal

Prevent tampered derived-publication runtime journals from selecting or recursively deleting paths
outside their publication generation directory during inspection or recovery.

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
- Valid prepared, published, complete, and stale-cleanup recovery behavior remains compatible.
- Focused publication, integrity, symlink-race, and full practical validation pass.

# Documentation impact

Status: none
Reason: This closes an implementation-level path-confinement defect without changing the
documented immutable-generation publication or recovery contract.

# Validation

```bash
.venv/bin/pytest -q tests/test_publication.py tests/test_publication_integrity.py
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: canonical Markdown remains authoritative; derived generations are disposable views.
- DD-052: derived publication is atomic and recoverable.
- LIFEOS-902: derived output publishes through immutable generations and one active pointer.
- LIFEOS-910: published generations are verified against an exact integrity inventory.
