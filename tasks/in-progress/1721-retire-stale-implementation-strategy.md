---
id: LIFEOS-1721
title: Retire stale implementation strategy document
status: in-progress
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove or consolidate `docs/implementation-strategy.md`, whose durable workflow guidance is now owned by `AGENTS.md` and `tasks/README.md` while its phase and Direction 6/7 release narrative is historical and stale.

# Scope

- Audit active references to `docs/implementation-strategy.md`.
- Remove the document if no current contract depends on it; otherwise reduce it to non-duplicative current guidance and move historical delivery detail out of the authoritative docs surface.
- Preserve completed task files as historical implementation evidence.

# Out of scope

- Rewriting `AGENTS.md` task workflow.
- Changing architecture or product behavior.
- Removing completed task history.

# Acceptance criteria

- Active documentation no longer states that only Phase 0 and Phase 1 are decomposed in detail.
- Direction 6/7 historical release-gate prose is not presented as a current implementation strategy unless still explicitly authoritative.
- Current development workflow has one clear source of authority without a competing strategy document.
- Manual links and project documentation checks pass.

# Documentation impact

Status: required

- `docs/implementation-strategy.md`: retire or reconcile the stale document.
- Any active document linking to it must be updated if the file is removed.

# Validation commands

- `python scripts/validate_tasks.py`
- `python scripts/validate_manual_links.py`
- `pytest -q tests/project`
- `git diff --check`

# Relevant decisions

- `AGENTS.md`: repository implementation workflow and source-of-authority rules.
- `tasks/README.md`: current task lifecycle contract.
