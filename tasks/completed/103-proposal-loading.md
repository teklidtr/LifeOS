---
id: LIFEOS-103
title: Proposal loading and structural validation
status: ready
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-102]
risk: low
affected_paths:
  - src/lifeos/proposals/loading.py
---

# Goal

Enable loading, parsing, and basic structural validation of proposals from disk, combining the schema and patch models.

# Scope

- Implement a loader that discovers all proposals in the `proposals/` directory.
- Parse `proposal.md` to extract metadata and the frontmatter `status`.
- Parse `patches.json` using the canonical schema deserializer.
- Perform structural validation:
  - Ensure the JSON conforms to the operations list.
  - Ensure `proposal.md` has the required frontmatter.
  - Reject corrupt or malformed proposals with a clear structural error without crashing the loader.

# Out-of-Scope

- Do not perform target-hash validation against live vault files.
- Do not perform SQLite indexing (this happens in LIFEOS-107).
- Do not perform ownership/managed-block validation.

# Acceptance Criteria

1. The loader successfully reads a valid proposal directory, instantiating the combined Proposal and Patch models.
2. The loader gracefully handles and reports missing `proposal.md`, missing `patches.json`, or malformed frontmatter.
3. The loader parses explicit operations correctly.

# Validation Commands

```bash
pytest tests/proposals/test_loading.py
```

# Relevant Design Decisions

- Proposal data is rebuildable entirely from the Git-tracked files; the loader is the single source of truth for constructing this state in memory.
