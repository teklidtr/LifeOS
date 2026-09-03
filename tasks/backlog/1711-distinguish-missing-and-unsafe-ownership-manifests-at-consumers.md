---
id: LIFEOS-1711
title: Distinguish missing and unsafe ownership manifests at consumers
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1668
risk: medium
---

# Goal

Make generated-ownership consumers distinguish a truly missing canonical manifest from an unsafe
filesystem entry without pathname-only existence checks.

# Problem and evidence

The LIFEOS-1668 consumer audit found several callers that test
`system/generated-ownership.json` with `Path.exists()` before entering the descriptor-safe
`GeneratedOwnership.load(...)` boundary:

- `src/lifeos/status.py::_ownership_status(...)`
- `src/lifeos/lint/linter.py::lint_vault(...)`
- `src/lifeos/facade/proposal_tools.py::_load_generated_ownership(...)`

`Path.exists()` returns false for a dangling symlink. As a result, an unsafe canonical manifest can
be reported as absent/missing, and lint can skip ownership-manifest validation entirely, even though
the secure ownership loader would reject the same path as unsafe. The facade path remains
fail-closed, but its diagnostic classification is still inaccurate.

This is independent of LIFEOS-1668's ownership-service hardening: LIFEOS-1668 explicitly keeps the
LIFEOS-1661 status routing behavior out of scope and audits consumers for compatibility rather than
redesigning their presence semantics.

# Scope

- Provide or reuse one descriptor-safe way to distinguish a missing canonical ownership manifest
  from an unsafe/unavailable manifest entry without a pathname-only authorization or diagnostic
  pre-check.
- Migrate status, lint, and proposal-tool ownership loading to that presence-aware boundary.
- Preserve the documented true-missing fallback and existing typed unsafe/invalid diagnostics.
- Add focused dangling-final-symlink and missing-manifest regressions for affected consumers.

# Out of scope

- Changes to generated-file ownership authority or mutation rules.
- Changes to the canonical manifest location.
- Ownership repair, release, regeneration, or migration.
- Broad status/lint formatting changes unrelated to manifest presence classification.

# Acceptance criteria

- A truly absent `system/generated-ownership.json` retains current status, lint, and proposal-tool
  behavior.
- A dangling final symlink or unsafe traversed manifest path is never classified as a clean/absent
  canonical manifest.
- Status and lint retain deterministic typed diagnostics and remain read-only.
- Proposal tooling remains fail-closed and distinguishes unsafe/invalid ownership state from true
  absence without reading through symlinks.
- Consumer regressions cover true missing, dangling symlink, and ordinary regular manifests.

# Documentation impact

Status: none
Reason: This corrects internal filesystem-state classification while preserving the documented
canonical ownership location and user workflow.

# Validation

```bash
rtk .venv/bin/pytest -q tests/status tests/lint tests/facade tests/ownership
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- DD-035: `system/generated-ownership.json` is durable canonical authorization data.
- `docs/safety-and-ownership.md`: unsafe filesystem state must not be reinterpreted as ownership
  authority.
- LIFEOS-1668: generated ownership itself uses a descriptor-safe filesystem boundary while
  preserving missing-manifest fallback.
- `AGENTS.md`: path traversal and symlink handling are security-sensitive and invariants should be
  enforced at coherent boundaries.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** The implementation is small but crosses status, lint, and
  proposal-tool diagnostic semantics around a security-sensitive filesystem boundary.
