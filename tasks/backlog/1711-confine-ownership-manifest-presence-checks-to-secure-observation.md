---
id: LIFEOS-1711
title: Confine ownership manifest presence checks to secure observation
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1668
risk: medium
---

# Goal

Make canonical generated-ownership consumers distinguish a genuinely missing manifest from unsafe
filesystem aliases without pathname-based presence checks that can bypass descriptor-safe
observation.

# Problem and evidence

LIFEOS-1668 moves `GeneratedOwnership.load(...)` behind descriptor-safe observation, but several
consumers still decide whether to call that boundary with `Path.exists()` first. A dangling symlink
at `system/generated-ownership.json` makes `Path.exists()` return false, so status can report healthy
`ownership-absent` and lint can skip ownership validation entirely instead of surfacing the unsafe
manifest path. The proposal facade also classifies that state as missing before secure loading,
although it remains fail-closed.

This is independent of the ownership service read/mutation hardening in LIFEOS-1668: the remaining
hazard is consumer-side presence classification before the canonical observation boundary.

# Scope

- Provide or reuse one descriptor-safe presence-aware generated-ownership load boundary that can
  distinguish securely absent manifests from present/unsafe manifests without caller `Path.exists()`
  prechecks.
- Migrate status, lint, and proposal-facade ownership consumers that currently preflight the
  canonical manifest with pathname presence checks.
- Preserve the established missing-manifest fallback and public diagnostic/error contracts for a
  genuinely absent canonical manifest.
- Surface dangling final symlinks and unsafe parent symlinks through the existing typed
  unsafe/invalid diagnostic paths rather than treating them as absence.
- Add focused regressions for true absence, dangling final symlinks, and unsafe parent components.

# Out of scope

- Changes to generated-file ownership authority, migration, repair, release, or regeneration.
- Changes to canonical manifest location or DD-035.
- Broad status/lint formatting changes unrelated to ownership presence classification.
- Broad vault I/O redesign.

# Acceptance criteria

- A genuinely absent `system/generated-ownership.json` retains current missing/empty fallback
  semantics in each consumer.
- A dangling final manifest symlink cannot be reported as healthy absence or skipped by lint.
- Unsafe/symlinked parent components cannot be collapsed into a missing-manifest result.
- Proposal tooling remains fail-closed and preserves its established public validation wording where
  compatible with the safer classification.
- No consumer performs pathname `exists()`/equivalent as authority for whether the canonical
  ownership manifest is safe to load.
- Focused status, lint, facade, and ownership regressions cover the secure presence boundary.

# Documentation impact

Status: none
Reason: This tightens internal classification of unsafe filesystem states while preserving the
existing documented canonical ownership location and user workflow.

# Validation

```bash
rtk .venv/bin/pytest -q tests/ownership tests/status tests/lint tests/facade
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- DD-035: durable generated ownership is canonical at `system/generated-ownership.json`.
- `docs/safety-and-ownership.md`: symlink/path trust boundaries fail closed and canonical ownership
  remains authoritative.
- LIFEOS-1668: descriptor-safe observation belongs in the ownership service; this follow-up confines
  consumer presence classification to that same boundary.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The implementation is localized but crosses status, lint, and
  proposal consumer contracts, so it needs careful compatibility and race-aware regression review.
