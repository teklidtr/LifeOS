---
id: LIFEOS-1650
title: Align bootstrap runtime example and optional feature defaults
status: completed
phase: hardening
depends_on:
  - LIFEOS-1634
risk: low
---

# Goal

Remove two small inconsistencies in the fresh-vault bootstrap contract: the example runtime directory must not imply that canonical proposals live under disposable `.lifeos/`, and `lifeos init` must leave optional Graphify/export features disabled unless the user explicitly enables them.

# Scope

- Update `.lifeos.example/README.md` so its runtime tree does not list a `.lifeos/proposals/` directory as proposal storage.
- Keep proposal validation/runtime diagnostics clearly distinct from canonical Git-tracked `proposals/<proposal-id>/` history.
- Change the generated `lifeos.yml` bootstrap defaults so `features.graphify` and `features.exports` are `false` by default.
- Add or update regression coverage for the generated configuration defaults.
- Update setup-facing documentation to state that fresh vaults keep optional Graphify/export features disabled until enabled by the user.

# Out of scope

- Changing the proposal engine, proposal paths, lifecycle, or validation storage.
- Removing Graphify or exports.
- Adding new feature flags or configuration UI.
- Migrating existing vaults or rewriting an existing `lifeos.yml`.

# Acceptance criteria

1. `.lifeos.example/README.md` no longer presents canonical proposal storage beneath `.lifeos/`.
2. Canonical proposal history remains documented as top-level `proposals/<proposal-id>/`; derived validation remains disposable runtime state.
3. A freshly initialized vault generates `features.graphify: false` and `features.exports: false`.
4. Existing configuration-loader defaults remain unchanged and consistent with the generated bootstrap.
5. Setup-facing documentation explains that Graphify and exports are opt-in after initialization.
6. Relevant bootstrap/integration tests and documentation validation pass.

# Documentation impact

Status: required

- `.lifeos.example/README.md`: correct the disposable runtime example and distinguish canonical proposal history from derived proposal validation state.
- `README.md`: document that fresh-vault Graphify/export flags are disabled until explicitly enabled.
- `docs/user-manual/04-setup-and-installation.md`: reviewed; no edit required because the existing manual already classifies Graph and export features as optional and does not claim they are enabled by default.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/integration/test_fresh_vault_setup.py
uv run python scripts/validate_manual_links.py
uv run ruff check src tests
uv run mypy src
```

# Relevant decisions

- DD-018: Graphify is a helper, not authority.
- DD-029: purpose-specific exports are optional.
- DD-031: proposals live in stable Git-tracked top-level `proposals/<proposal-id>/` folders.
- DD-034: proposal validation is derived runtime state under `.lifeos/proposal-validation/`.
- DD-088 / LIFEOS-1634: `lifeos init` owns a minimal, deterministic, non-destructive fresh-vault bootstrap contract.

# Completion notes

Implemented on PR #23.

- Removed the stale `.lifeos/proposals/` entry from the disposable runtime example and documented root `proposals/<proposal-id>/` as canonical history with `.lifeos/proposal-validation/` as derived state.
- Changed the first-party bootstrap to generate `features.graphify: false` and `features.exports: false` for fresh vaults.
- Added fresh-vault integration assertions for both parsed feature flags and generated YAML text.
- Updated setup-facing README guidance; the full setup manual was reviewed and already described Graph/export support as optional.
- Repository-wide seam searches found no runtime/code path using `.lifeos/proposals` as a proposal store; remaining explicit `true` feature-flag uses are opt-in/test scenarios rather than bootstrap defaults.
- Local checkout validation could not run in the execution environment because `github.com` DNS resolution was unavailable; this limitation was recorded in the PR before CI.
- PR `fast-checks` passed on the reviewed implementation head `ccb56fca9ab2711a2e7cb1f89d90c137c8c74218`.
- Codex review of that implementation head reported no major issues.
- Full validation run `33345614333` passed all four pytest shards, aggregate `full-test`, clean-room setup/MCP, home-node service container, and ARM64 image-build gates.
