---
id: LIFEOS-500
status: completed
phase: 6
title: Adaptive daily planning menus
---

## Goal

Build realistic daily menus from plan-embedded actions using time, energy, motivation, due dates, modes, and blockers.

## Scope

- Parse typed actions from plan frontmatter.
- Filter blocked, completed, and over-capacity actions.
- Rank eligible actions deterministically.
- Produce a bounded daily menu with selection reasons and deferral diagnostics.
- Add `lifeos plan today` text and JSON output.

## Out of scope

- Automatically changing task status.
- Calendar writes.
- Treating hobbies, exercise, or study as mere productivity inputs.

## Acceptance criteria

- Energy and motivation remain distinct.
- Blockers and time budgets are enforced.
- Output is a proposed menu, not an imperative schedule.
- Repeated task records stay in their plan notes.
- Unit and CLI tests pass.
