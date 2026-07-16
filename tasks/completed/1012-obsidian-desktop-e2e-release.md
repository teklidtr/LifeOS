---
id: LIFEOS-1012
title: Complete desktop end-to-end testing, packaging, and release
status: backlog
phase: 10
depends_on:
  - LIFEOS-1003
  - LIFEOS-1004
  - LIFEOS-1005
  - LIFEOS-1006
  - LIFEOS-1007
  - LIFEOS-1008
  - LIFEOS-1009
  - LIFEOS-1010
  - LIFEOS-1011
risk: high
---

# Goal

Ship the Obsidian-native daily interaction layer as a reproducible desktop
release with cross-component tests, upgrade behavior, clear installation, and a
safe fallback path.

# Scope

- Add end-to-end tests covering plugin, bridge, Python services, canonical vault,
  registry rebuilding, proposal lifecycle, and recovery.
- Test the complete daily loop:
  - open Today
  - check in
  - capture
  - choose work
  - record outcomes
  - reconcile unaccounted items
  - complete a study session
  - run a weekly review
  - review and apply a proposal
- Add fixture vaults for empty, typical, malformed, stale, blocked, and corrupt
  states.
- Add deterministic protocol-compatibility and upgrade tests.
- Define versioning for plugin, bridge protocol, Python package, and persisted
  runtime schemas.
- Produce installable Obsidian plugin artifacts and the supported Python/bridge
  distribution.
- Add first-run setup, upgrade, uninstall, backup, and troubleshooting
  documentation.
- Update `docs/user-manual/` so routine usage is Obsidian-first and CLI commands
  are clearly secondary, including the architecture, feature reference, setup,
  daily workflow, weekly review, proposal review, attention reconciliation, and
  troubleshooting sections.
- Preserve chapter navigation and validate every internal manual link.
- Add release checks that prevent publishing incompatible artifacts.

# Out of scope

- Mobile parity.
- Cloud accounts or remote sync.
- Public plugin-store submission unless separately approved.
- Semantic retrieval workspace.
- Adaptive learning from execution history.

# Required invariants

- A failed upgrade leaves canonical Markdown intact and supports rollback.
- Removing the plugin or bridge leaves the vault readable and editable.
- Runtime and registry state can be rebuilt after deletion.
- Version mismatch fails clearly rather than producing partial behavior.
- Release artifacts are reproducible from committed source and lockfiles.
- No test depends on the user's real vault or private data.

# Required tests

- Fresh install and first-run setup.
- Upgrade from the previous supported protocol and runtime schema.
- Incompatible upgrade rejection.
- Plugin disable/uninstall and reinstallation.
- Bridge crash during read and write interactions.
- Obsidian edit racing a dashboard action.
- Full proposal interruption and recovery from the UI.
- Registry deletion and deterministic rebuild.
- OS notification service install/uninstall smoke tests.
- Accessibility and keyboard-only critical-path checks.

# Acceptance criteria

- A new user can install and operate the daily loop without terminal commands
  after setup.
- Supported desktop platforms pass documented smoke tests.
- The user manual, architecture, and troubleshooting guide match shipped
  behavior.
- Full Python and TypeScript suites, builds, diff checks, and release validation
  pass.

# Validation commands

```bash
pytest -q
ruff check src tests
mypy src
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
./scripts/validate-release.sh
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-007: Native Obsidian references first
- DD-011: Read before write
- DD-031: Git-tracked proposals and stable layout
- DD-033: SQLite disposability and rebuilding
