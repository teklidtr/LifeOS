---
id: LIFEOS-1615
title: Wire deterministic registry refresh into CLI and MCP
status: completed
phase: 16
depends_on:
  - LIFEOS-005
  - LIFEOS-006
  - LIFEOS-107
risk: medium
---

# Goal

Expose the existing deterministic vault and proposal registry refresh through
supported user and agent entry points.

# Scope

- Add one shared facade operation that initializes and refreshes disposable
  registry state from canonical vault files and proposals.
- Add `lifeos scan` as a thin CLI adapter with human-readable and JSON results.
- Add an idempotent `registry_refresh` MCP tool for connected agents.
- Preserve MCP-only semantic ingestion: no model runtime, API key, or ingestion
  CLI is introduced.
- Update setup, workflow, and troubleshooting documentation.
- Add focused facade, CLI, and MCP tests.

# Out of scope

- Watching filesystem events continuously.
- Rebuilding semantic retrieval, graph, export, or other derived products.
- Changing canonical Markdown or proposal lifecycle state.

# Acceptance criteria

- A file move is reported as one new path and one deleted path in `registry.db`.
- Repeating the refresh is idempotent.
- CLI and MCP call the same facade operation.
- MCP tool metadata identifies the operation as non-canonical and idempotent.
- Existing ingestion and proposal behavior remains unchanged.

# Validation commands

```bash
pytest tests/facade/test_registry_tools.py tests/cli/test_scan_cli.py tests/mcp/test_server.py -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-033: SQLite disposability and rebuilding
- DD-036: Python is the sole business-rule engine
- DD-079: Agent-assisted ingestion is MCP-only

# Implementation record

- Added a shared derived-write facade used by both CLI and MCP.
- Added `lifeos scan [--config PATH] [--json]`.
- Added idempotent, non-destructive MCP tool `registry_refresh` and made it the
  first advertised ingestion step.
- Updated architecture, setup, feature, workflow, and troubleshooting docs.
- Verified the command against the configured LifeOS vault; the existing moved
  study paths were unchanged on the repeated scan.

# Validation record

- Focused and impacted regression tests: 281 passed.
- Full suite with unique-module import mode: 1,375 passed in the sandbox; the
  single Unix-socket sandbox denial passed when rerun outside the sandbox.
- Ruff passed for every changed Python and test file.
- Mypy passed for the new facade and changed MCP server. Full-project mypy and
  Ruff remain blocked by pre-existing errors recorded in LIFEOS-1616.
- `git diff --check` passed.
