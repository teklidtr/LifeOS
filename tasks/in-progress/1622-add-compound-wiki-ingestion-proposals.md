---
id: LIFEOS-1622
title: Add compound wiki ingestion proposals
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1613
  - LIFEOS-1619
risk: medium
---

# Goal

Let an external MCP agent create one detailed wiki page and update one exact
section in an existing human-owned wiki note through a single atomic draft
proposal containing two typed operations.

# Scope

- Add a deterministic compound ingestion builder with exactly one
  `create_generated_file` and one base-hash-bound `patch_human_file` operation.
- Verify one registered study source and retain it as proposal provenance.
- Require an absent `wiki/` create target plus an existing human-owned `wiki/`
  update target and one exact ATX heading.
- Expose the compound path through typed facade and MCP contracts while keeping
  the existing create-only and update-only tools backward compatible.
- Teach MCP instructions and user documentation when to choose the compound path.
- Add focused builder, facade, MCP, and lifecycle application coverage.

# Out of scope

- Autonomous target-note or heading discovery inside LifeOS.
- Updating more than one existing section or existing target.
- Direct mutation, automatic submission, approval, or application.
- Replacing generated-owned files that already exist.

# Acceptance criteria

- The compound tool rejects an unregistered source, present create target,
  missing update target, missing/duplicate heading, managed-block target, or
  unchanged replacement body without persisting a proposal.
- The draft contains exactly two ordered operations: `create_generated_file`
  followed by `patch_human_file`.
- The human-file patch is bound to the existing target's current SHA-256 hash and
  changes only the selected heading body.
- Source provenance, generated ownership identity, and both target paths remain
  inspectable in proposal metadata.
- Submit, approve, and apply create and patch both targets atomically through the
  existing proposal lifecycle.
- Existing ingestion tools and contracts remain compatible.

# Validation

```bash
uv run pytest -q tests/ingestion tests/facade/test_proposal_tools.py tests/mcp tests/integration/test_mcp_ingestion_lifecycle.py
uv run ruff check <changed Python files>
uv run mypy <changed source files>
uv run python scripts/validate_manual_links.py
git diff --check
```

# Relevant decisions and policy

- DD-003 and DD-004: consequential changes remain reviewable and explicitly applied.
- DD-011 and DD-032: human edits remain hash-bound typed patches.
- DD-017: original study sources remain immutable.
- DD-031 and DD-034: proposal state and validation remain canonical and fail closed.
- DD-079: agent-assisted ingestion remains MCP-only and stops at draft.
- `docs/safety-and-ownership.md`: human-owned wiki content is never silently rewritten.
