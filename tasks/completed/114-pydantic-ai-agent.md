---
id: LIFEOS-114
title: Pydantic AI Agent
status: completed
depends_on: [LIFEOS-113.1, LIFEOS-113.2]
---

# Objective
Provide the shared Pydantic AI runtime boundary used by LifeOS AI adapters.

# Scope to evaluate
- optional Pydantic AI dependency and packaging strategy
- model/provider configuration
- dependency injection
- typed result handling
- tool registration through LIFEOS-113
- provider-independent stable errors
- secret redaction
- deterministic fake-model testing
- no live network calls in the normal test suite

# Non-goals
- ingestion-specific prompts or output schema
- CLI command
- MCP transport
- automatic approval or application
- provider-specific business logic in core LifeOS services

LIFEOS-203 will own the ingestion-specific adapter and prompt/schema behavior.

# Completion Evidence
- **Implementation Commit Hash**: `0e741ee71f57a1509a88cfea7ba371d405f5c1c4`
- **Exact Implementation Files**:
  - `pyproject.toml`
  - `src/lifeos/ai/__init__.py`
  - `src/lifeos/ai/errors.py`
  - `src/lifeos/ai/runtime.py`
  - `tests/ai/test_runtime.py`
- **Resolved Pydantic AI version**: `2.9.0` (pydantic-ai-slim)
- **Optional Dependency Declaration**: `pydantic-ai-slim` added to `[project.optional-dependencies] ai` in `pyproject.toml`
- **Focused Test Count**: 5 passed (`tests/ai/test_runtime.py`)
- **Full-Suite Count**: 452 passed
- **Ruff Output**: All checks passed!
- **Mypy Output**: Success: no issues found in 43 source files
- **Confirmation**: `ALLOW_MODEL_REQUESTS = False` disables real model requests in tests. Tests use `TestModel` and `FunctionModel`.
- **Confirmation**: No ingestion-specific prompts or schemas are included (runtime accepts injected `instructions` and `output_type`).
- **Confirmation**: Clean working-tree status.
- **UserError Behavior**:
  - **Where raised**: In the `vault_read_markdown` tool wrapper within `src/lifeos/ai/runtime.py` (`_vault_read_markdown`).
  - **What condition it terminates**: Terminate retry loops entirely when an unrecoverable failure occurs (e.g. `ToolExecutionError`, `ToolUnavailableError`).
  - **Propagation**: Caught explicitly by `run_lifeos_agent_sync` to translate its `__cause__` back into a stable `LifeOSAIToolError`, abstracting `pydantic-ai` internals away from the caller.
  - **Why it hides sensitive details**: It ensures that provider-facing exceptions or internals (such as Pydantic AI's retry prompts or payload errors) don't bleed back to the business logic, instead translating into clean `LifeOSAIToolError` types.
  - **Why arbitrary programming errors remain visible**: We do not catch `Exception`, ensuring actual runtime logic bugs bubble up properly without being masked by standard exception paths.

*Note: Reclassified as part of the optional embedded-agent branch.*
