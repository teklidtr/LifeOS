---
id: LIFEOS-204
title: Wiki proposal generation
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-201, LIFEOS-202, LIFEOS-111]
risk: medium
---

# Objective
Convert a validated `AnalysisResult` into a canonical proposal that creates a provenance-bearing wiki page.

# Scope
- Generate a proposal using existing proposal APIs and v2 patch schema.
- Use a generated-file operation.
- Embed canonical LIFEOS-201 provenance in candidate Markdown.
- Carry generator ID and version through ownership.
- Write only proposal documents; never create final wiki page directly.
- Explicitly set initial lifecycle state to `draft` (or document `submitted` if chosen). Do not use `pending`.

# Expected files
- `src/lifeos/ingestion/proposals.py`
- `tests/ingestion/test_proposals.py`

# Non-goals
- Approval or application
- Direct wiki-file creation
- SQLite writes, AI provider invocation, CLI parsing

# Acceptance criteria
- Proposal loads through canonical loader.
- v2 patches validate; target page not written before application.
- Source provenance and ownership metadata included.
- Proposal proceeds through existing APIs.

# Focused test plan
- valid draft proposal
- canonical loader round trip
- v2 patch validation
- deterministic candidate Markdown
- provenance included
- ownership metadata included
- final wiki target absent before application
- approval and application compatibility through existing APIs

Implementation has not begun.
