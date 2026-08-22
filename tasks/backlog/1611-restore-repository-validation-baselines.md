---
id: LIFEOS-1611
title: Restore repository validation baselines
status: backlog
risk: medium
---

# Objective

Restore clean default full-suite pytest collection and repository-wide strict
mypy validation.

# Scope

- Configure pytest so same-named test modules in different directories collect
  without import-file mismatches.
- Resolve the existing strict mypy findings across bridge, reviews, feedback,
  daily, copilot, and attention modules.
- Preserve runtime behavior while adding focused regression coverage where a
  typing fix exposes ambiguity.

# Non-goals

- Changing MCP routing or proposal semantics.
- Broad feature refactoring unrelated to validation findings.

# Acceptance criteria

- `uv run pytest -q` collects and passes without import-file mismatches.
- `uv run mypy src` passes with no errors.
- `uv run ruff check .` passes.
- The import-mode choice is documented in project configuration.

# Validation commands

```bash
uv run pytest -q
uv run mypy src
uv run ruff check .
```

# Relevant decisions

- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-012: Preservation checks are scripted.
