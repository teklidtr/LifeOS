---
id: LIFEOS-1610
title: Package the OpenAI provider in the AI extra
status: backlog
depends_on: [LIFEOS-114, LIFEOS-203, LIFEOS-206]
risk: low
---

# Objective

Make the documented OpenAI ingestion setup install every runtime dependency
required by the `openai:` model provider.

# Scope

- Add the Pydantic AI OpenAI provider dependency to the `ai` optional extra.
- Update the lockfile.
- Add an installation test that constructs an `openai:` backend without making
  a model request.
- Keep the setup manual aligned with the packaged dependency.

# Non-goals

- Sending a real model request.
- Storing or validating a user's API key.
- Adding providers other than OpenAI.

# Acceptance criteria

- `uv sync --extra ai` installs the OpenAI client dependency.
- `get_analysis_backend(..., model_spec="openai:gpt-4o")` can construct the
  backend when supplied a dummy key, without an import error.
- Core installation without the `ai` extra remains provider-free.
- Focused tests and the full test suite pass.

# Validation commands

```bash
uv sync --extra dev --extra ai
uv run pytest -q tests/ingestion/test_backend_factory.py tests/cli/test_ingest_cli.py
uv run pytest -q
uv run ruff check .
uv run mypy src
```

# Relevant decisions

- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-053: Model adapters are optional and provider-neutral.
