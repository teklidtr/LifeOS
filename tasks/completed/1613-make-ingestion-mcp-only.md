---
id: LIFEOS-1613
title: Make ingestion MCP-only
status: completed
milestone: maintenance
depends_on: [LIFEOS-113.3, LIFEOS-115.1]
---

# Goal

Remove the embedded API-key/model ingestion path so external Codex-style agents
can ingest registered sources only through the bounded LifeOS MCP workflow.

# Scope

- Remove the `lifeos ingest` CLI command and its API-key/model backend.
- Remove ingestion-only Pydantic AI runtime code and packaging dependencies.
- Preserve registered-source verification, proposal construction, provenance,
  the typed facade, and the MCP ingestion tools.
- Update architecture, setup, feature, workflow, and troubleshooting documentation
  so MCP is the only documented ingestion entry point.
- Replace deleted-path tests with guards that keep embedded ingestion from returning.

# Out of scope

- Changing proposal submit, approve, or apply semantics.
- Removing provider-neutral optional adapters from unrelated subsystems.
- Automatically transitioning or applying ingestion proposals.

# Acceptance criteria

- `lifeos ingest` is not advertised or accepted by the CLI.
- Core installation has no Pydantic AI dependency or ingestion model/API-key path.
- MCP advertises and completes `vault_read_markdown` followed by
  `ingestion_create_wiki_proposal` while stopping at draft.
- No ingestion documentation instructs users to configure an AI provider or API key.
- Source immutability, provenance, and proposal validation remain intact.

# Validation

```bash
uv run pytest -q tests/cli tests/facade tests/ingestion tests/mcp tests/integration/test_mcp_ingestion_lifecycle.py
uv run pytest --import-mode=importlib -q
uv run ruff check <changed Python files>
uv run mypy <changed source files>
uv run python scripts/validate_manual_links.py
```

Repository-wide default pytest collection, Ruff, and strict mypy baseline work
remains owned by backlog task LIFEOS-1611 and is outside this task's scope.

# Validation evidence

- Focused CLI, facade, ingestion, MCP, and MCP lifecycle suites: 242 passed.
- Full regression suite with importlib collection: 1,369 passed.
- Task-scoped Ruff: passed.
- Task-scoped strict mypy: passed across all changed source files.
- Manual links: all links across 14 chapters validated.
- CLI smoke test: help omits `ingest`; attempting it exits with argparse code 2.
- Source and lock audit: no Pydantic AI dependency, embedded agent runtime,
  model environment variable, API-key variable, or analysis backend remains.
- The default full-suite collection collision and repository-wide pre-existing
  Ruff/mypy findings were reproduced and remain tracked by LIFEOS-1611.

# Relevant decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-003: Durable proposal mode.
- DD-004: Proposal application is explicit.
- DD-017: Original sources remain immutable.
- DD-036: Python is the sole business-rule engine.
- DD-037: Default desktop transport is vault-scoped STDIO.
- DD-079: Agent-assisted ingestion is MCP-only.
- LIFEOS-113.3 trust boundary: external agents supply title/body while LifeOS
  owns verification, identity, provenance, and draft persistence.
