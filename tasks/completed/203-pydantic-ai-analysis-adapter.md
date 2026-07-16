---
id: LIFEOS-203
title: Pydantic AI Analysis Adapter
status: completed
depends_on: [LIFEOS-114, LIFEOS-202]
---

# Objective
Implement the `AnalysisBackend` protocol using Pydantic AI.

# Scope
- Implement the `AnalysisBackend` protocol inside `src/lifeos/ingestion/pydantic_ai_backend.py`.
- Ensure it wraps the underlying `run_lifeos_agent_sync` logic to return the structured `WikiPageDraft` and associated `ProvenanceGenerator` info.
- Error translation from core AI runtime exceptions to `AnalysisBackendError`.

# Non-goals
- Ingestion CLI logic
- Actual web search/tools
- Pydantic AI shared boundaries

# Completion Evidence
- **Implementation Commit**: `0d4a9a3`
- **Counts**: 9 focused tests passed, 461 full-suite tests passed.
- **Linters**: Ruff and Mypy passed clean.
- **Model Isolation**: Model is explicitly injected. No provider keys or connection logic implemented here.
- **Provenance Contract**: Generator is stamped with explicitly defined `GENERATOR_ID`, `ADAPTER_VERSION`, and `PROMPT_SCHEMA_VERSION`. 
- **Prompt Isolation**: Deterministic JSON serialization guarantees `markdown_body` cannot bleed into configuration context.
- **Strict Limits Enforced**: Explicit finite usage limits (`request_limit=8`, `tool_calls_limit=8`) are strictly applied.
- **Structural Protocol Validation**: Test suite validates structure without module-level fake instantiation.
- **Robust Error Translation**: Native AI exceptions explicitly caught and translated to stable `AnalysisBackendError`; internal logic errors propagate natively.
- **Clean Extensibility**: No optional module leaks; missing `pydantic-ai` does not crash `lifeos.ingestion` import.
- **Side-effects verified**: Test suite verifies zero actual filesystem modification during analysis.

*Note: Reclassified as part of the optional embedded-agent branch.*
