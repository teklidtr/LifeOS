---
id: LIFEOS-202
title: Typed analysis backend and source orchestration
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-201, LIFEOS-116]
risk: medium
---

# Objective
Create an AI-provider-independent ingestion service that loads one registered Markdown source and requests a structured wiki analysis.

# Scope
- Define a typed protocol `AnalysisBackend`.
- Define immutable models: `AnalysisRequest`, `AnalysisResult`, `WikiPageDraft`, `source identity and hash`.
- Choose one verified source-state mechanism (read-only registry hash lookup or LIFEOS-116 comparison API).
- Orchestration must: accept canonical source path, confirm registration, confirm hash matches, load Markdown safely, construct request, call backend, validate result, perform no canonical writes.
- Add a deterministic fake backend for tests.

# Expected files
- `src/lifeos/ingestion/models.py`
- `src/lifeos/ingestion/analysis.py`
- `tests/ingestion/test_analysis.py`

# Non-goals
- Direct Pydantic AI dependency
- Prompt-provider configuration
- Proposal creation, CLI command, or registry insertion

# Acceptance criteria
- Unregistered, missing, or changed sources are rejected.
- Valid source produces a typed result.
- Orchestration performs no canonical writes.
- Fake backend enables deterministic tests.
- No model-provider details leak into core ingestion.

# Focused test plan
- registered unchanged source accepted
- unregistered source rejected
- missing source rejected
- changed source rejected
- path outside vault rejected
- deterministic fake backend
- backend result validation
- zero canonical writes
- no provider-specific imports in core orchestration

Implementation has not begun.

LIFEOS-202 requires the public read-only source comparison contract from
LIFEOS-116. Its production implementation must not be built against a mocked
registry API.


## Completion Evidence

- Implementation commit: b45a17d62e3f89a2c6bc38d9ea068a7e29dac409
- 15 focused tests passed in `test_orchestration.py`
- 392 full-suite tests passed
- Ruff passed
- mypy passed
- source bytes are read exactly once
- analyzed bytes match the registry-verified hash
- Markdown is parsed in memory without reopening the source
- orchestration performs no registry or canonical writes
- core ingestion imports no Pydantic AI code
- `AnalysisBackendError` propagates unchanged
- arbitrary backend programming errors are not relabeled
