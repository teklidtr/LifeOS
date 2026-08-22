---
id: LIFEOS-1630
title: Propose reviewed wiki tags during ingestion
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1629
risk: medium
---

# Goal

Let an external MCP agent inspect source `tags` and `topics`, improve weak source
taxonomy, and propose the final canonical wiki `tags` as an explicit part of the
ordinary ingestion proposal.

# Scope

- Expose only normalized source `tags` and `topics` beside the bounded Markdown
  body returned by the read facade and MCP tool.
- Add optional proposed wiki tags and a visible rationale to create, compound
  create, and generated-owned section-update ingestion contracts.
- Validate proposed tag syntax, bounds, normalization, and uniqueness
  deterministically.
- Write accepted proposed tags to wiki frontmatter and show source taxonomy,
  proposed tags, and rationale in the proposal body and immutable operation diff.
- Permit tag revision during an existing generated-owned wiki replacement while
  preserving exact-section update semantics; never let ingestion rewrite tags on
  a human-owned wiki target.
- Preserve backward compatibility for callers and legacy proposals that omit tag
  fields.
- Index the accepted canonical `tags` through the existing retrieval path.

# Out of scope

- Treating agent-proposed tags as source facts.
- A global taxonomy or automatic retagging of unrelated wiki notes.
- Direct mutation of generated or human-owned wiki files outside proposals.
- Indexing source-only `topics` as canonical wiki tags without proposal review.

# Acceptance criteria

- A source with `tags` and/or `topics` exposes both to the MCP agent without
  exposing unrelated frontmatter.
- The agent may retain, remove, combine, or add proposed tags even when source
  taxonomy exists.
- New wiki and compound-create proposals include canonical `tags` in the exact
  reviewed diff.
- A generated-owned section update may revise tags in the same full-file typed
  replacement; a human-owned target rejects requested tag changes.
- Missing source taxonomy and omitted proposed tags remain valid and do not invent
  metadata.
- Invalid, duplicate, excessive, or non-normalized proposed tags fail before a
  proposal directory is published.

# Relevant decisions and policy

- DD-002: semantic interpretation remains separate from deterministic facts.
- DD-003 and DD-004: consequential metadata changes use explicit proposals.
- DD-079 and DD-081: ingestion is MCP-only and ownership-aware.
- DD-083: exact reviewed operation diffs remain immutable history.
- `docs/safety-and-ownership.md`: generated ownership and human content boundaries.
