---
id: LIFEOS-300
status: completed
phase: 4
title: Deterministic routing and context packs
---

## Goal

Build deterministic lexical routing and inspectable context packs from canonical Markdown notes.

## Scope

- Search Markdown by title, description, path, and body terms.
- Assemble policy, evidence excerpts, omissions, and evidence-gap signals.
- Add a `lifeos context build` CLI command with text and JSON output.

## Out of scope

- Embedding models or remote vector stores.
- Graph-derived authority.
- Consequential vault mutation.

## Acceptance criteria

- Search order is deterministic.
- Context packs identify source paths and excerpts.
- Missing or narrow evidence is explicitly reported.
- Hidden runtime and Git directories are excluded.
- CLI and unit tests pass.

## Validation

```text
uv run pytest tests/context tests/cli/test_context_cli.py -q
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```
