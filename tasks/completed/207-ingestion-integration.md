---
id: LIFEOS-207
title: MCP-driven end-to-end ingestion lifecycle
status: backlog
milestone: phase-3-first-ingestion
depends_on: [LIFEOS-115, LIFEOS-205]
risk: low
---

# Objective
Prove the complete ingestion lifecycle using the STDIO MCP adapter and the proposal facade.

# Scope
- Start the LifeOS MCP server via a test-owned helper.
- Connect an external MCP client.
- Use `ingestion_create_wiki_proposal`, `proposal_submit`, `proposal_approve`, and `proposal_apply` tools to complete the lifecycle.
- Verify the final provenance and registry indices.

# Expected files
- `tests/integration/test_mcp_lifecycle.py`

# Non-goals
- Live model network calls
- Testing the embedded AI agent path
- Direct Python service imports for the core flow (must use MCP JSON-RPC boundary)

# Acceptance criteria
- Complete lifecycle succeeds strictly through MCP tool calls.
- Proposal is created, approved, and applied successfully.
- Final page is traceable to source in the registry.

# Focused test plan
- Start MCP adapter in test harness
- Client calls `ingestion.create_wiki_proposal`
- Client calls `proposals.approve_proposal`
- Client calls `proposals.apply_proposal`
- Verify `wiki/target.md` created with correct provenance
- Verify registry query matches applied state
- No direct service logic or SQLite shortcuts used
- No embedded AI network calls

Implementation has not begun.
