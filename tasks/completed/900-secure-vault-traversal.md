---
id: LIFEOS-900
title: Secure descriptor-based vault traversal
status: completed
phase: hardening
depends_on: []
risk: high
---

# Goal

Create one symlink-safe, vault-bounded traversal and read layer for every
read-only or derived LifeOS feature.

# Discovered issue

Several domain modules discover notes with `Path.rglob()`, check them with
`Path.is_file()`, and later open them by path. A symlink inside the vault can
therefore refer to a file outside the vault and be read, indexed, graphed, or
exported. Even callers that resolve and check containment before opening retain
a time-of-check/time-of-use window.

Affected areas include:

- `src/lifeos/context/search.py`
- `src/lifeos/study/review.py`
- `src/lifeos/planning/menu.py`
- `src/lifeos/observation/patterns.py`
- `src/lifeos/graph/views.py`
- `src/lifeos/exports/bundles.py`
- `src/lifeos/facade/read_only.py`

# Scope

- Define a shared vault traversal API rooted at an already validated vault.
- Traverse with directory descriptors and no-follow semantics on POSIX.
- Reject symlinked files, symlinked directories, and paths that escape the
  configured vault.
- Read canonical Markdown through descriptors rather than unrestricted path
  reopening.
- Preserve deterministic ordering and stable vault-relative paths.
- Define whether an unsafe entry aborts a build or is skipped with an explicit
  finding; apply that policy consistently per product.
- Migrate context, study, planning, observation, graph, export, and facade
  readers to the shared API.
- Keep generated runtime directories outside canonical source traversal.

# Out of scope

- Supporting non-POSIX filesystems.
- Following symlinks intentionally.
- Changing canonical Markdown formats.
- Adding write access to read-only features.
- Claiming protection from a compromised process with equivalent filesystem
  permissions.

# Required tests

- File symlink inside the vault targeting an external Markdown file.
- Directory symlink inside the vault targeting an external directory.
- Symlink swapped between discovery and read.
- Nested normal directories and files remain readable.
- Deterministic ordering is unchanged.
- Every migrated consumer either reports or rejects unsafe entries according
  to its documented policy.
- Facade reads cannot escape the vault under concurrent symlink replacement.
- Descriptor ownership and close-on-error paths are verified.

# Acceptance criteria

- No migrated source-discovery path uses unrestricted `Path.rglob()` followed
  by path-based reopening for canonical content.
- No symlinked canonical source is consumed by context packs, study sessions,
  daily planning, observation, graph builds, exports, or facade reads.
- Unsafe filesystem state produces typed, sanitized diagnostics.
- Existing deterministic outputs remain byte-for-byte stable for ordinary
  vaults.

# Validation commands

```bash
pytest tests/context tests/study tests/planning tests/observation tests/graph tests/exports tests/facade
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-011: Read before write
- DD-017: Original sources remain immutable
- DD-029: Optional purpose-specific exports
