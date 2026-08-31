---
id: LIFEOS-1650
title: Align bootstrap runtime example and optional feature defaults
status: in-progress
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
- Update setup documentation to state that fresh vaults keep optional Graphify/export features disabled until enabled by the user.

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
5. Setup documentation explains that Graphify and exports are opt-in after initialization.
6. Relevant bootstrap/integration tests and documentation validation pass.

# Documentation impact

Status: required

- `.lifeos.example/README.md`: correct the disposable runtime example.
- `docs/user-manual/04-setup-and-installation.md`: document opt-in fresh-vault feature defaults.

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
