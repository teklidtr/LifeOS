---
id: LIFEOS-1637
title: Add first-party `lifeos doctor` runtime readiness checks
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1634
  - LIFEOS-1636
risk: medium
---

# Goal

Add a deterministic, read-only `lifeos doctor` command that answers whether the installed
LifeOS application and a selected vault are ready for normal local use.

A user should not need to manually infer compatibility from Python, Git, bootstrap shape,
registry/recovery state, or optional MCP installation. The command should compose existing
status diagnostics with installation/runtime checks and produce actionable text and stable
JSON without mutating the vault or external client configuration.

# Design principles

- Doctor is diagnostic, not repair.
- Reuse authoritative deterministic status/bootstrap contracts instead of duplicating them.
- Canonical Markdown and external client configuration remain untouched.
- Missing optional capabilities are reported distinctly from blocking core failures.
- Human-readable output and JSON represent the same typed result.
- Do not place an LLM in the diagnostic or test loop.

# Scope

- Add a supported CLI surface:

  ```bash
  lifeos doctor [--config PATH] [--json]
  ```

  with `lifeos.yml` as the default config path.
- Add a typed doctor result model and deterministic collector that reports at minimum:
  - installed LifeOS version;
  - supported Python runtime status;
  - Git executable availability;
  - configuration load/readability;
  - whether the configured vault satisfies the current first-party bootstrap shape;
  - existing vault health by composing the authoritative `status` collector, including
    registry, lint, generated ownership, recovery, and configured derived-feature checks;
  - optional MCP SDK/package availability;
  - `lifeos-mcp` executable availability and the vault-scoped command shape needed by an
    external MCP client.
- Promote or expose the existing bootstrap-recognition predicate so `init` and `doctor`
  share one bootstrap-shape contract instead of reimplementing canonical roots/files.
- Classify findings so blocking core readiness failures produce a non-zero exit code while
  missing optional MCP support or not-yet-built optional derived outputs remain actionable
  non-blocking diagnostics unless an existing status contract already treats the vault as
  blocked.
- Keep the command read-only: do not initialize/refresh/rebuild registries, create runtime
  state, edit canonical Markdown, install dependencies, initialize Git, or write external
  MCP/Obsidian/Codex/Claude configuration.
- Add focused unit/CLI tests plus fresh-vault integration coverage using the real
  `lifeos init` bootstrap.
- Update Setup & Installation and README quick-start guidance to use `lifeos doctor` as the
  post-bootstrap readiness check and explain its diagnostic-only boundary.

# Out of scope

- Automatically repairing failed checks.
- Automatically installing Git, Python packages, MCP support, or the Obsidian plugin.
- Editing Codex, Claude, Cursor, Obsidian, shell, or other external client configuration.
- Replacing `lifeos status`; `doctor` composes status with environment/setup readiness.
- Performing LLM-quality evaluation.
- Starting a long-lived MCP server or exposing a network service.
- Vault schema migration or upgrade automation.

# Acceptance criteria

- `lifeos doctor --config <vault>/lifeos.yml` works from outside the vault working directory.
- A fresh valid `lifeos init` vault is recognized through the same bootstrap-shape contract
  used by initialization.
- Invalid/missing configuration, unsupported Python, missing Git, invalid bootstrap shape,
  and blocking vault health produce deterministic finding codes and non-zero exit status.
- Optional MCP absence is clearly reported without pretending the core local vault is
  unusable.
- When MCP support is available, doctor reports the resolved local server executable and a
  vault-scoped registration command shape without editing any client config.
- Existing `collect_status()` semantics remain authoritative for vault subsystem health;
  doctor does not maintain a second implementation of registry/ownership/recovery/lint logic.
- `--json` emits a stable machine-readable representation containing overall readiness,
  application/environment findings, vault findings, and next actions.
- Human-readable output identifies blocking failures, warnings/optional gaps, and next
  actions without exposing canonical note bodies or secrets.
- Doctor performs no canonical writes, runtime repair/rebuild writes, or external client
  configuration changes.
- README and Setup & Installation document the supported command and its diagnostic-only
  behavior.
- Normal CI and Docker clean-room setup/MCP gates remain green.

# Documentation impact

Status: required

- `README.md`: add `lifeos doctor` to the fresh-vault quick start/readiness flow.
- `docs/user-manual/04-setup-and-installation.md`: document doctor output, exit semantics,
  optional MCP readiness, and the no-repair/no-client-mutation boundary.
- `docs/architecture.md`: record doctor as a read-only composition of bootstrap,
  environment, and existing status contracts if implementation introduces a durable
  diagnostic boundary worth documenting.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/cli tests/integration/test_fresh_vault_setup.py
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- DD-033: SQLite is disposable and rebuildable; doctor may inspect it but must not make it
  canonical or silently repair it.
- DD-035: generated ownership is canonical authorization data and invalid ownership fails
  closed.
- DD-036: Python remains the sole business-rule engine; desktop clients should not
  reimplement readiness semantics.
- DD-087: clean-room setup/MCP validation is deterministic infrastructure testing, not an
  LLM-quality gate.
- DD-088: vault bootstrap is first-party, deterministic, non-destructive, and does not
  mutate external client configuration.
- LIFEOS-1636 reconciled current setup, registry, MCP, bootstrap, and operational docs with
  shipped behavior; 1637 should extend those current contracts rather than revive stale
  setup paths.
