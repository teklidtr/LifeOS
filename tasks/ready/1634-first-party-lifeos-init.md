---
id: LIFEOS-1634
title: Add first-party `lifeos init` vault bootstrap
status: ready
phase: 16
depends_on:
  - LIFEOS-1633
risk: medium
---

# Goal

Replace error-prone manual vault bootstrap steps with a first-party `lifeos init` command.
LifeOS itself should own the canonical bootstrap contract instead of delegating it to an
external template engine such as Cookiecutter.

A new user should be able to create a valid vault with one command while preserving the
runtime, MCP, and semantic contracts established by LIFEOS-1633.

# Design principles

- Bootstrap is a LifeOS domain operation, not a generic project-template operation.
- Keep the generated surface minimal and deterministic.
- Do not introduce Cookiecutter, Jinja, or another template-engine dependency.
- Generated top-level roots provide LifeOS domain context; they do not prescribe a
  universal ontology or fixed substructure inside `wiki/`, `study/`, or other roots.
- Existing user content must never be overwritten implicitly.
- Deterministic integration tests, not an LLM, define whether a generated vault is valid.

# Scope

- Add a supported CLI entry point:

  ```bash
  lifeos init [PATH]
  ```

  where an explicit path can be used non-interactively by tests and automation.
- Move the canonical bootstrap definition into application code rather than duplicating
  literal setup contents across documentation and tests.
- Create the current canonical vault roots used by the LIFEOS-1633 contract:
  `journal/`, `raw/`, `study/`, `wiki/`, `flashcards/`, `patterns/`, `profile/`,
  `goals/`, `plans/`, `experiments/`, `metrics/`, `reviews/`, `proposals/`, and
  `system/`.
- Generate the canonical bootstrap files:
  - `lifeos.yml` with relative `vault_root: .` and `.lifeos` runtime state
  - minimal vault-root `AGENTS.md`
  - `system/instructions.yml`
  - `system/generated-ownership.json`
  - `.gitignore` covering disposable LifeOS/runtime/editor state
- Make initialization fail closed for unsafe or conflicting existing targets. Re-running
  against an already valid initialized vault may report that state without rewriting
  user-controlled content, but partial/conflicting scaffolds must not be silently repaired
  or overwritten.
- Update the fresh-vault integration test to exercise the real `lifeos init` command
  instead of a test-local `_bootstrap_vault()` implementation.
- Keep the Docker clean-room setup/MCP gate exercising the same real bootstrap path.
- Simplify Setup & Installation documentation around `lifeos init` and remove manual
  `mkdir`/file-copy scaffolding instructions.
- Keep MCP client registration explicit and testable after vault creation rather than
  mutating external client configuration implicitly.

# Out of scope

- Cookiecutter or another external template engine.
- Reworking runtime policy, `vault_context`, study evolution, or MCP semantics established
  by LIFEOS-1633.
- Choosing or enforcing a universal wiki/study folder taxonomy beneath canonical roots.
- Automatically editing Codex, Claude, Obsidian, shell, or other external application
  configuration.
- Destructive `--force` behavior that overwrites an existing vault.
- Vault migrations or upgrades for older initialized vaults; those should use an explicit
  future migration contract rather than overloading `init`.

# Acceptance criteria

- `lifeos init <path>` creates a valid fresh vault without manual directory or file setup.
- The generated vault loads through `load_config()` with the vault root and `.lifeos`
  runtime resolved relative to the generated `lifeos.yml`.
- The command can be executed deterministically and non-interactively in pytest and the
  Docker clean-room gate.
- Generated bootstrap files match one application-owned canonical definition rather than
  separate copies embedded in tests and documentation.
- A generated vault passes the same scan, status, context, MCP handshake/tool-call, and
  study workflow contracts used by the LIFEOS-1633 clean-room integration tests.
- Existing non-empty/conflicting targets fail without overwriting user files.
- Re-running against an already initialized valid vault is non-destructive and has a
  deterministic outcome.
- No Cookiecutter/Jinja/template-engine runtime dependency is added.
- Setup documentation presents `lifeos init` as the primary fresh-vault path and no longer
  requires users to hand-create the canonical roots or bootstrap files.
- CI remains green for both the normal test job and `docker-setup-e2e`.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/integration/test_fresh_vault_setup.py
uv run pytest --import-mode=importlib -q
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```
