---
id: LIFEOS-1632
title: Add compounding multi-page wiki ingestion
status: backlog
phase: 16
depends_on:
  - LIFEOS-1631
risk: high
---

# Goal

Let one reviewed ingestion integrate a registered source across the persistent
wiki rather than treating ingestion as one source to one page.

# Scope

- Let an external MCP agent propose a bounded set of source, entity, concept, and
  synthesis page creations and ownership-aware existing-page updates in one
  atomic proposal.
- Keep every page operation individually inspectable and source-grounded.
- Add deterministic limits that prevent ontology explosion and unbounded fan-out.
- Preserve provenance per page and proposal-wide related-source evidence.
- Define how index/overview maintenance participates without becoming a second
  source of truth.

# Out of scope

- Autonomous approval or application.
- A universal entity or concept ontology.
- Creating pages for every extracted named entity or keyword.

# Acceptance criteria

- One source may reviewably touch multiple useful wiki pages while preserving the
  existing ownership, stale-target, immutable-diff, and recovery guarantees.
- The agent must justify page creation/update selection and remain within a
  deterministic operation budget.
- Existing single-page ingestion tools remain compatible.

# Validation

Define focused ingestion, proposal, MCP, recovery, and end-to-end coverage when
this task is promoted to `ready/`.

# Relevant decisions and policy

- DD-079, DD-081, DD-083, DD-084.
- `docs/vision.md`: LifeOS is not a giant universal ontology.
