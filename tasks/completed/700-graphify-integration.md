---
id: LIFEOS-700
status: completed
phase: 8
title: Optional Graphify-compatible graph views
---

## Goal

Build replaceable structural graph views with stable IDs and dirty-state tracking without treating graph inference as authority.

## Scope

- Extract nodes, wikilinks, and explicit typed relations from Markdown.
- Maintain separate graph views under `.lifeos/graphify/`.
- Track source hashes and clean/dirty/missing state.
- Add `lifeos graph build` and `lifeos graph status` commands.

## Out of scope

- Remote Graphify installation or APIs.
- Promoting inferred edges into canonical notes.
- Editing source Markdown.

## Acceptance criteria

- Graph outputs are deterministic JSON.
- Views remain separate.
- Source changes mark a view dirty.
- Graph output is derived and disposable.
- Unit and CLI tests pass.
