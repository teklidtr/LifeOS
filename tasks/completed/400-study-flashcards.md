---
id: LIFEOS-400
status: completed
phase: 5
title: Study and flashcard review workloads
---

## Goal

Turn due flashcards into bounded review sessions instead of one task per card.

## Scope

- Parse flashcard Markdown frontmatter.
- Select due cards deterministically.
- Group cards into topic workloads under a time budget.
- Add `lifeos study review` text and JSON output.

## Out of scope

- Remote spaced-repetition services.
- Mutating card schedules.
- Agent-generated card content.

## Acceptance criteria

- Future cards are excluded.
- Overdue cards are prioritized deterministically.
- Workloads group multiple cards by topic.
- Time budgets are respected.
- Unit and CLI tests pass.
