---
id: LIFEOS-1619
title: Support existing wiki section updates during ingestion
status: ready
milestone: maintenance
depends_on: [LIFEOS-111, LIFEOS-113.3, LIFEOS-115.1, LIFEOS-1613]
---

# Goal

Let an external MCP agent turn a registered study source into a reviewable,
base-hash-bound update of one explicitly selected section in an existing
human-owned wiki note.

# Scope

- Add a deterministic ingestion proposal builder that replaces the body of one
  exact Markdown heading while preserving the heading and all other content.
- Represent the change as `patch_human_file`, bound to the current target hash.
- Verify the registered source through the existing ingestion trust boundary and
  retain it in proposal `related_sources` metadata.
- Expose the operation through the typed facade and a strict MCP tool that stops
  at a draft proposal.
- Document when ingestion should create a wiki page and when it should propose an
  update to an existing section.
- Add focused facade, ingestion, MCP, and lifecycle coverage.

# Out of scope

- Autonomous target-note or heading discovery inside LifeOS.
- Whole-document semantic merging or updating multiple sections in one call.
- Direct target mutation, automatic submission, approval, or application.
- Updating generated-owned files or content inside managed blocks.
- Changing the existing create-only ingestion tool contract.

# Acceptance criteria

- The update tool requires an explicit registered source, existing `wiki/`
  target, exact heading, and replacement section body.
- Exactly one matching heading is required; missing or duplicate matches fail
  without persisting a proposal.
- The proposal contains one `patch_human_file` operation with the target's
  current SHA-256 base hash and a unified diff that changes only that section.
- Frontmatter, other headings, citations, stable IDs, and user-owned sections
  outside the selected section remain byte-for-byte unchanged.
- Managed-block or generated-owned targets are rejected by the existing proposal
  validation boundary.
- The source remains unchanged and is recorded in proposal metadata.
- MCP advertises both create and section-update ingestion paths and both stop at
  draft status.
- Documentation no longer implies that ingestion can only create a new wiki page.

# Validation

```bash
uv run pytest -q tests/ingestion tests/facade/test_proposal_tools.py tests/mcp tests/integration/test_mcp_ingestion_lifecycle.py
uv run ruff check <changed Python files>
uv run mypy <changed source files>
uv run python scripts/validate_manual_links.py
git diff --check
```

# Relevant policy and decisions

- `docs/safety-and-ownership.md`: human-owned files require reviewable,
  target-bound proposals and preservation checks.
- DD-003: consequential edits use durable proposals.
- DD-004: proposal application is explicit.
- DD-011: updates to human-owned files use base-hash-bound patches.
- DD-017: original sources remain immutable.
- DD-036: Python is the sole business-rule engine.
- DD-037: the Obsidian plugin remains a thin desktop client.
- DD-079: agent-assisted ingestion is MCP-only.
