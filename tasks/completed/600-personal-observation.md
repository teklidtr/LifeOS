---
id: LIFEOS-600
status: completed
phase: 7
title: Tentative personal pattern analysis
---

## Goal

Surface cautious, evidence-counted personal patterns from journal metrics without presenting correlation as causation.

## Scope

- Parse dated journal observations with numeric metrics and activity tags.
- Analyze numeric associations and tagged group differences.
- Require minimum sample sizes and report caveats.
- Add `lifeos observe patterns` text and JSON output.

## Out of scope

- Medical diagnosis or causal claims.
- Automatic promotion of candidate patterns into canonical truth.
- Editing journal or pattern notes.

## Acceptance criteria

- Findings are always marked candidate.
- Evidence counts and effect direction are explicit.
- Weak or insufficient evidence returns no finding plus a reason.
- Unit and CLI tests pass.
