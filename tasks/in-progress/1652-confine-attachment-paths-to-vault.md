---
id: LIFEOS-1652
title: Confine attachment storage paths to the vault
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-1602
risk: critical
---

# Goal

Prevent persisted attachment metadata or filesystem indirection from causing LifeOS to read,
write, extract, recover, or delete files outside canonical attachment storage.

# Scope

- Validate attachment manifest and original paths as canonical, portable vault-relative paths.
- Restrict attachment manifest references to `attachments/manifests/` and original paths to
  `attachments/originals/`.
- Route attachment reads, extraction, recovery hashing, imports, and deletion through a shared
  descriptor-based boundary that rejects symlinks in every path component.
- Preserve content-hash and byte-size verification on the same pinned file used for extraction.
- Add regression coverage for traversal, absolute and Windows-style paths, non-canonical aliases,
  storage-root escapes, symlinked parents, external-file deletion, and normal extraction behavior.

# Out of scope

- Changing the documented attachment layout or schema version.
- Changing capture privacy, retrieval eligibility, or provider-preview policy.
- Refactoring unrelated canonical Markdown mutation paths.
- Changing merge, split, cancellation, checkpoint, or lock semantics.

# Acceptance criteria

- Attachment contracts reject any manifest path outside `attachments/manifests/` and any original
  path outside `attachments/originals/`.
- Traversal, absolute, Windows-drive, backslash, repeated-separator, and dot-segment paths fail
  closed before filesystem access.
- A symlink in any original path component cannot be used to import, audit, extract, recover, or
  delete an external file.
- Extraction parses the exact descriptor-pinned bytes that passed hash and size verification.
- Valid attachments retain existing import, audit, extraction, recovery, and deletion behavior.
- Focused tests, Ruff, mypy, and the broad practical local pytest suite are run before completion.

# Documentation impact

Status: none
Reason: This hardening restores the already documented vault-relative, collision-safe attachment
layout and bounded local-read contract; it does not change user-visible behavior or a documented
schema, architecture, setup, CLI, MCP, or operational contract.

# Validation

```bash
.venv/bin/pytest -q tests/captures/test_artifact.py tests/captures/test_storage_processing.py tests/captures/test_privacy_migration_recovery.py tests/test_vault.py
.venv/bin/pytest -q tests/captures tests/bridge/test_capture_bridge.py tests/integration/test_cross_component_edges.py -k 'capture or attachment or extraction or privacy or recovery'
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: Markdown vault files remain canonical human-readable state.
- DD-074: Attachment originals use deterministic vault-relative paths and manifests point to them.
- `docs/rich-capture-architecture.md`: canonical attachment paths are vault-relative and original
  reads are local and bounded.
- `docs/safety-and-ownership.md`: canonical content and human-authored state must not be silently
  rewritten or exposed through derived workflows.
