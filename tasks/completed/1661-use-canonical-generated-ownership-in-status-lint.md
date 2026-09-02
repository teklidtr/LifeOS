---
id: LIFEOS-1661
title: Use canonical generated ownership in status lint
status: completed
phase: hardening
depends_on:
  - LIFEOS-109
  - LIFEOS-907
risk: medium
---

# Goal

Make status diagnose generated-file integrity using the canonical ownership manifest,
without repairing ownership or introducing a second verifier.

# Problem and evidence

`src/lifeos/status.py:266`, `_lint_status`, passes
`config.runtime_dir / "ownership.json"` to `lint_vault`.
`_ownership_status` (line 309) uses canonical
`system/generated-ownership.json`, but only validates manifest structure.

The existing linter in `src/lifeos/lint/linter.py:126` already detects missing owned
files and content-hash mismatches. With a valid canonical manifest and a modified
owned file, status returned `lint-clean` with zero errors and `ownership-valid`;
calling that same linter with the canonical manifest returned
`ownership-hash-mismatch`. A stale runtime manifest can also influence status
despite having no authority.

# Scope

- Route status lint through `vault_root / DEFAULT_OWNERSHIP_MANIFEST_PATH`, using
  the existing constant from `lifeos.ownership.manifest`.
- Keep both status ownership checks aligned with that single canonical location.
- Reuse the existing ownership linter and add status-level regression coverage.

# Out of scope

- Ownership migration, automatic repair, release, or regeneration of missing files.
- New ownership validation logic or changes to generated-file mutation authority.
- Unrelated status formatting or diagnostic refactoring.

# Acceptance criteria

- Matching canonical ownership remains clean; missing owned files and changed
  hashes produce the existing meaningful status diagnostics.
- Malformed canonical manifests retain typed, partial diagnostics.
- Missing canonical manifests retain the documented human-owned fallback.
- Misleading, malformed, or stale runtime ownership files cannot affect results.
- Custom/external runtime directories behave identically.
- Status remains read-only: verify canonical files and manifests retain bytes and
  mtimes. Preserve deterministic text/JSON output, diagnostic shapes, and exit policy.
- Extend `tests/status/test_status.py`; reuse cases represented by
  `tests/lint/test_linter.py` for valid, missing, and changed owned files.

# Documentation impact

Status: none
Reason: This restores DD-035's already documented canonical manifest location and
uses existing integrity diagnostics; it introduces no new ownership workflow,
configuration, or output contract.

# Validation

```bash
rtk .venv/bin/pytest -q tests/status tests/lint tests/ownership
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

The validated implementation head `224d6dfd1a46a7bf31ecf6db21e35068b554027d` passed current-head
fast-checks run `33674425687`, including the documentation-impact gate, manual-link validation,
Ruff, mypy, Python compilation, full test collection, and project contract smoke tests.

Full-validation run `33674478852` passed on that same head: all four full pytest shards, aggregate
`full-test`, clean-room setup/MCP, the home-node service container, and the ARM64 home-node image
build completed successfully.

The normal Codex review cycle found two blocking P1 issues introduced/exposed by routing status lint
to canonical ownership. The first preserved partial status diagnostics when canonical ownership
path safety fails; the second replaced unsafe pathname hashing of owned targets with the existing
descriptor-based `observe_vault_file(...)` boundary. Both findings were addressed with focused
regressions and their review threads were resolved. Final normal Codex re-review on the unchanged
`224d6dfd1a46a7bf31ecf6db21e35068b554027d` head returned a clean PR-level approval reaction with
no new review findings.

The separate security review was not run. On 2026-09-02 the repository owner explicitly instructed
the implementation agent to skip it for this task; this is recorded as a user-authority workflow
override under `AGENTS.md`, not as a successful security-review result.

Local repository execution remained unavailable in the implementation environment because the
execution container could not resolve `github.com` during checkout. Repository CI therefore supplied
the executable validation layer, and this limitation is recorded rather than represented as local
validation.

The cross-cutting filesystem audit also identified pre-existing hazards in
`GeneratedOwnership.load(...)` and `GeneratedOwnership.write_generated_file(...)` that are
independent of LIFEOS-1661's status-lint caller. They were recorded as backlog task LIFEOS-1668 and
were intentionally not implemented in this PR.

# Relevant decisions

- DD-035: durable generated ownership is canonical in
  `system/generated-ownership.json`, not disposable runtime state.
- `docs/architecture.md`, Registry: SQLite cannot become ownership authority.
- `docs/safety-and-ownership.md`, Fully generated files: status must not repair or
  release ownership, including orphaned entries.
- `AGENTS.md`: derived state must not become canonical mutation authority.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** The defect is a localized path mismatch and the
  correct verifier already exists. The main work is explicit regression coverage
  and preservation of status diagnostics, not architectural redesign.
