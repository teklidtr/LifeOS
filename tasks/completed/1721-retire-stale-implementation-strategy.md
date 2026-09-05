---
id: LIFEOS-1721
title: Retire stale implementation strategy document
status: completed
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

# Completion evidence

- Removed `docs/implementation-strategy.md`; the stale Phase 0/1 statement and historical Direction 6/7 release-gate narrative are no longer presented as current implementation strategy.
- Repository-wide reference audit found no active documentation dependency on the retired file. The reference in `tasks/completed/001-verify-project-skeleton.md` was preserved as historical implementation evidence.
- PR #60 `PR checks` run `33979180251` passed on head `45725015e2afa0f035ee4d08aa597dae42d34088`, including task workflow validation, documentation-impact gate, manual-link validation, Ruff, mypy, Python compilation, pytest collection, `tests/project`, and the Obsidian plugin checkpoint.
- `git diff --check` passed against a local reconstruction of the exact PR diff after direct checkout was unavailable because this execution environment could not resolve `github.com`.
- PR #60 `Full validation` run `33979194447` passed on head `45725015e2afa0f035ee4d08aa597dae42d34088`, including all four full pytest shards, the aggregate `full-test` gate, clean-room setup/MCP validation, home-node service-container validation, and ARM64 home-node image build.
- A normal `@codex review` was requested after the implementation stabilized, but Codex reported that the account had reached its code-review usage limit and produced no review. On 2026-09-05 the user explicitly instructed the implementation agent to finish the task without waiting for Codex, overriding that review requirement for this task.
- Security review was skipped per the user's explicit instruction for this development sequence.
- No independent follow-up work was discovered that required a new backlog task.
