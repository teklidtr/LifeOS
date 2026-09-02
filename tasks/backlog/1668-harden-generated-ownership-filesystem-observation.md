---
id: LIFEOS-1668
title: Harden generated ownership filesystem observation
status: backlog
phase: hardening
depends_on:
  - LIFEOS-109
risk: high
---

# Goal

Make `GeneratedOwnership` inspect its manifest and existing owned targets without following
symlinks, blocking on special files, or trusting pathname observations that can race.

# Problem and evidence

The LIFEOS-1661 review audit found two pre-existing ownership-layer filesystem hazards outside
that task's status-lint scope:

- `GeneratedOwnership.load(...)` uses `Path.exists()` and `Path.read_bytes()` after only checking
  symlink path components. A FIFO, device, socket, or other non-regular manifest entry can still be
  opened through the normal blocking file API. Every caller of `GeneratedOwnership.load(...)`
  inherits that behavior, including status, proposal review snapshots, ownership reconciliation,
  and proposal tooling.
- `GeneratedOwnership.write_generated_file(...)` checks path components for symlinks but hashes an
  existing owned target with `stream_sha256(...)`. An owned FIFO/device/special file can therefore
  block or be read through a filesystem object that is not a regular canonical vault file.

LIFEOS-1661 confines its fix to lint-time owned-target observation by reusing the descriptor-based
vault read primitive. The ownership service itself still needs one coherent filesystem boundary.

# Scope

- Centralize manifest reads and existing-owned-target observations on the repository's secure,
  descriptor-based vault filesystem primitives or an equivalent single ownership-layer boundary.
- Reject symlinks in the complete traversed path and reject non-regular manifest/target entries
  before reading or hashing bytes.
- Preserve stable missing-manifest fallback, manifest parsing, ownership authorization, generator
  checks, content-hash semantics, persistence behavior, and public exception contracts unless a
  narrowly required safety classification is documented and migrated together.
- Audit every `GeneratedOwnership.load(...)` consumer and every `stream_sha256(...)` ownership
  mutation use before review.
- Add focused regressions for symlinked parents/final entries, FIFO/special entries, and pathname
  replacement races where the existing secure primitive exposes a deterministic test seam.

# Out of scope

- Changes to which files may be generated or who authorizes generated-file mutation.
- Ownership migration, repair, release, or regeneration policy.
- Status formatting or the LIFEOS-1661 canonical-manifest routing fix.
- Broad vault I/O redesign unrelated to generated ownership.

# Acceptance criteria

- Loading a missing ownership manifest retains the current empty-manifest fallback.
- Loading a manifest never follows symlinks or blocks on non-regular filesystem entries; unsafe and
  unavailable states surface through stable typed ownership errors.
- Existing owned-target verification before mutation never follows symlinks or reads non-regular
  files and remains race-aware at the established vault boundary.
- Normal regular-file manifests and generated targets retain current hashes, generator checks,
  timestamps, persistence semantics, and caller-visible behavior.
- `GeneratedOwnership.load(...)` consumers remain compatible or are migrated together with focused
  regressions.
- Tests cover final symlinks, parent symlinks, FIFO/special entries, missing entries, ordinary
  regular files, and relevant race/error seams.

# Documentation impact

Status: none
Reason: This is internal filesystem hardening of the existing generated-ownership contract; it does
not change the documented ownership location, authorization model, configuration, or user workflow.

# Validation

```bash
rtk .venv/bin/pytest -q tests/ownership tests/proposals tests/status tests/lint
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- DD-035: `system/generated-ownership.json` is durable canonical authorization data.
- `docs/safety-and-ownership.md`: generated-file ownership must not overwrite or reinterpret unsafe
  filesystem state.
- `AGENTS.md`: filesystem access, path traversal, and symlink handling are security-sensitive; one
  invariant should be enforced at one coherent boundary rather than through accumulating call-site
  guards.
- LIFEOS-1661 review audit identified the pre-existing ownership-layer variants while fixing the
  status-lint caller.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** This is a compact but security-sensitive consolidation across
  a shared ownership service and several consumers. The implementation should reuse established
  descriptor-based vault I/O while preserving exception and mutation semantics.
