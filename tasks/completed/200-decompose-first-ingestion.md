---
id: LIFEOS-200
title: Decompose the first ingestion vertical slice
status: completed
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-100]
risk: medium
---

# Goal

Create implementation tasks for:

```text
Markdown study source
  → registered
  → analyzed
  → wiki proposal
  → approved
  → applied
  → indexed with provenance
```


## Completion Evidence
- Decomposition commit hash: 8140a5a
- LIFEOS-201 through LIFEOS-207 created
- Canonical provenance assigned to Git-tracked wiki frontmatter
- SQLite classified as derived
- Core analysis separated from Pydantic AI
- No ingestion code implemented
