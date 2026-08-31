# LifeOS

LifeOS is a private, local, Obsidian-native system for durable knowledge, study and
flashcards, adaptive planning, journals and metrics, personal observation, experiments,
rich capture, evidence-grounded conversations, and proposal-based agent assistance.

Its purpose is to help the user understand how they work, not merely maximize task
completion.

## Application repository vs vault

This repository contains the **LifeOS application**. Your personal Markdown belongs in a
separate **LifeOS vault**. The application supplies deterministic business rules, CLI tools,
the optional Obsidian plugin, a local STDIO MCP server, and an optional authenticated
always-on MCP home-node service. The vault remains portable canonical Markdown plus a small
amount of Git-tracked system metadata.

Agent-assisted ingestion is MCP-only. LifeOS does not embed an ingestion model runtime or
require a provider API key. External agents connect through local STDIO or the authenticated
home-node MCP transport and can produce reviewable proposals; they do not silently rewrite
canonical notes.

## Quick start

Requirements: Python 3.11+, Git, and preferably `uv`.

Install the application:

```bash
uv sync
source .venv/bin/activate
```

Create a separate vault with the first-party bootstrap, then run the read-only readiness
check before populating disposable runtime state:

```bash
lifeos init ~/LifeOS-vault
lifeos doctor --config ~/LifeOS-vault/lifeos.yml
cd ~/LifeOS-vault
lifeos scan --config ./lifeos.yml
lifeos status
```

`lifeos init` is non-destructive. It creates the supported canonical bootstrap roots and
files, initializes Git, and refuses to overwrite a conflicting or partial vault. Re-running
it on a recognized LifeOS vault does not restore template text over your edits. Fresh vaults
leave the optional Graphify and export feature flags disabled in `lifeos.yml`; enable them
explicitly when you want those derived features.

`lifeos doctor` is diagnostic only. It checks the installed LifeOS/Python/Git environment,
first-party vault bootstrap shape, existing vault health, and optional MCP availability. It
does not repair the vault, build disposable indexes, install dependencies, or mutate Codex,
Claude, Obsidian, or another external client's configuration. Use `--json` for a stable
machine-readable result.

For MCP-assisted workflows, install the optional MCP dependency in the application
repository and register `lifeos-mcp` with your client explicitly:

```bash
cd /absolute/path/to/lifeos-application
uv sync --extra mcp
```

Local STDIO remains the simplest first-class mode. For an always-on Linux/NAS/Raspberry
Pi-class node, `lifeos serve` exposes the same deterministic MCP/facade/business-rule core
over authenticated Streamable HTTP with a deliberately narrower network capability set. It
binds only to loopback by default, requires a bearer secret from an environment variable or
secret file, records a stable configured actor in disposable remote activity, permits remote
proposal submission, and omits `proposal_approve`/`proposal_apply` from the home-node tool
surface. The supplied `deploy/home-node/` OCI/Compose deployment keeps host publication on
loopback by default and is validated for `linux/arm64` as part of full validation.

See the Setup & Installation Guide for the tested local registration command, home-node
container deployment, authentication/TLS/private-network guidance, vault/runtime boundaries,
Home Assistant Yellow path, doctor exit semantics, and Obsidian plugin installation.

## User documentation

- [Complete User Manual](docs/user-manual/README.md)
- [Setup & Installation](docs/user-manual/04-setup-and-installation.md)
- [Step-by-Step Workflow](docs/user-manual/05-workflow.md)
- [Obsidian Desktop Cockpit](docs/user-manual/06-obsidian-desktop.md)
- [Generated Wiki Source History / References](docs/user-manual/14-generated-wiki-source-history.md)
- [System architecture](docs/architecture.md)
- [Design decisions](docs/design-decisions.md)

## Development

When changing the LifeOS application itself:

1. Read `AGENTS.md`.
2. Read `docs/vision.md` and the relevant architecture/design documentation.
3. Select exactly one task from `tasks/ready/`.
4. Follow the task lifecycle and documentation-impact rules in `tasks/README.md`.

Small verifiable tasks evolve the application; completed task files are implementation
history, not a substitute for current user or architecture documentation.

### Continuous integration

Pull requests targeting `master` use two validation levels:

- `fast-checks` runs on ordinary PR open, reopen, and synchronize events. It keeps the
  documentation-impact gate, manual-link validation, Ruff, mypy, compileall, pytest
  collection, and the project contract smoke tests. A documentation-only diff confined to
  allowlisted Markdown under `docs/` or the task lifecycle, plus `README.md`/`AGENTS.md`, can
  skip dependency installation and Python application checks. Implementation-owned Markdown
  such as `prompts/`, `packages/`, workflow files, and either endpoint of a code-to-doc rename
  remains on the full fast-check path. Documentation checks always run with the runner's
  standard Python.
- A full checkpoint is requested by adding the `full-validation` label to the PR. That event
  runs the complete pytest suite across four stateless `full-test-shard-*` runners plus the
  clean-room `docker-setup-e2e` gate. The Docker gate also exercises the authenticated
  home-node image, restart/runtime-rebuild behavior, and a real `linux/arm64` image build.
  The aggregate `full-test` check succeeds only when every pytest shard succeeds. If material
  commits land after a successful checkpoint, remove and re-add `full-validation` to validate
  the new head without creating a dummy commit. Other label events do not emit the required
  `full-test` or `docker-setup-e2e` check names.
- Every push to `master` and every manual `workflow_dispatch` of the full-validation workflow
  runs the complete full checkpoint automatically.

The pytest shards partition the collected suite by count with an exact-pinned `pytest-split`
version. They do not use test-result, affected-test, or duration-history caches, so every full
checkpoint executes every collected test and has no cache state that can change test selection.
The separate full-path `pytest --collect-only` pass is intentionally omitted because each shard
performs normal pytest collection before execution; the fast PR path keeps collect-only as its
cheap import/collection contract.

The fast and full PR workflows share the same concurrency group with asymmetric cancellation.
A requested full checkpoint does not cancel an in-progress `fast-checks` run for the same head;
it waits for that required feedback to finish. A later PR synchronization starts a new
`fast-checks` run with cancellation enabled, so an obsolete in-progress full checkpoint is still
cancelled when a newer commit makes it irrelevant.

`astral-sh/setup-uv` dependency caching remains enabled. `.mypy_cache` is additionally cached
as disposable performance state. Its primary key includes runner/Python/dependency/configuration
inputs, a PR-or-branch scope, and the current commit. Each new commit can therefore restore the
most recent compatible scoped cache and, after mypy runs, publish a fresh immutable snapshot;
an exact rerun of the same commit can reuse the primary key directly. Restore keys deliberately
omit the commit suffix so incremental reuse survives source edits. Cache restoration never
skips mypy, and a miss or eviction changes only CI speed. Ruff and pytest result caches are not
persisted.

The Docker checkpoint keeps the clean-room setup/MCP gate and authenticated native home-node
runtime gate uncached as behavioral integration checks. Its real `linux/arm64` home-node build
uses a BuildKit GitHub Actions layer cache scoped to the ARM64 image. That cache contains only
rebuildable image layers and is performance state, not validation evidence: the ARM64 build
command still executes at every full checkpoint, a cache miss simply rebuilds the layers, and a
failed cache-backed build is retried without remote cache. The ARM64 validation uses a
cache-only BuildKit output because importing the image into the runner daemon solely to inspect
the architecture would add work without increasing the guarantee already established by the
explicit `linux/arm64` build target.

`master` currently has no repository-enforced required status checks, so merge readiness is
also governed by the PR workflow in `AGENTS.md`. If branch protection is enabled later, use
unique check names and require `fast-checks`, `full-test`, and `docker-setup-e2e`; the latter
two appear for PRs only after the explicit full-validation checkpoint.
