---
id: LIFEOS-1626
title: Make ingestion proposals ownership-aware
status: backlog
phase: 16
depends_on:
  - LIFEOS-1622
risk: high
---

# Goal

Prevent MCP ingestion from creating drafts whose operation type conflicts with
durable generated ownership, and define a bounded update route for an existing
generated-owned wiki note.

# Scope

- Check `system/generated-ownership.json` while building create, section-update,
  and compound ingestion proposals.
- Refuse an absent create target that still has a durable ownership entry with
  a specific remediation diagnostic.
- Never emit `patch_human_file` for a generated-owned target.
- Define and implement the bounded proposal operation used when ingestion must
  update a generated-owned wiki note.
- Cover facade, MCP, preflight, and user-facing guidance with tests.

# Out of scope

- Silently deleting or reconstructing durable ownership entries.
- Weakening target hashes or application-time ownership checks.
- Whole-vault ownership reconciliation.

# Acceptance criteria

- Every ingestion proposal emitted by MCP can pass ownership preflight when its
  targets remain unchanged.
- Generated-owned targets are never represented as human-file patches.
- Orphaned ownership produces a precise diagnostic and no unusable draft.
