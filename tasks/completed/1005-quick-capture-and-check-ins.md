---
id: LIFEOS-1005
title: Add Obsidian quick capture and daily check-ins
status: backlog
phase: 10
depends_on:
  - LIFEOS-1001
  - LIFEOS-1003
  - LIFEOS-1004
risk: high
---

# Goal

Let the user capture thoughts and record morning or evening state from Obsidian
through small guided forms that produce valid canonical Markdown without
requiring manual frontmatter editing.

# Scope

- Add a global quick-capture modal for:
  - thought or inbox note
  - task attached to an existing plan
  - new project seed
  - journal observation
  - flashcard draft
  - metric or activity entry
- Add morning and evening check-in cards to the Today dashboard.
- Use domain-specific forms rather than a generic arbitrary frontmatter editor.
- Validate stable IDs, dates, metrics, durations, energy, motivation, paths, and
  source references through Python contracts.
- Preview the canonical target and resulting change before submission when an
  existing note will be modified.
- Provide idempotent retry and clear conflict resolution when the target changed
  in another Obsidian pane.
- Open the created or updated note after successful capture.
- Make required fields minimal and place optional detail behind progressive
  disclosure.

# Out of scope

- AI classification of captures.
- Meal-photo analysis or attachment ingestion.
- Automatic creation of fully decomposed plans.
- Generic edits to arbitrary Markdown.
- Background reminders.

# Required invariants

- A capture is written once even if the UI retries after a lost response.
- Tasks remain embedded in their canonical plan files.
- Journal metrics honor metric definitions when available.
- A cancelled modal causes no write.
- Existing human prose and unrelated frontmatter remain unchanged.
- Direct human capture cannot silently create an approved proposal.

# Required tests

- Capture each supported type from an empty and populated vault.
- Duplicate submit after timeout does not duplicate content.
- Concurrent note edit produces a conflict UI with reload and retry options.
- Invalid metric, duration, path, and plan selection fail before write.
- Keyboard-only completion and modal cancellation.
- Morning and evening check-ins update the correct date across midnight and
  timezone boundaries.
- Created note opens at the expected file or block.

# Acceptance criteria

- Routine capture and check-in require no terminal or YAML editing.
- Canonical output is valid under existing parsers and domain loaders.
- Conflict and retry behavior are visible and safe.
- Python and plugin tests pass.

# Validation commands

```bash
pytest tests/daily tests/markdown tests/planning tests/study -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-006: Stable IDs are selective
- DD-011: Read before write
- DD-023: Tasks stay with plans
- DD-028: Metric definitions act like data types
