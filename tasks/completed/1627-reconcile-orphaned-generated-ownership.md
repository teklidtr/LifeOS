---
id: LIFEOS-1627
title: Reconcile orphaned generated ownership
status: completed
phase: 16
depends_on:
  - LIFEOS-1626
risk: high
---

# Goal

Provide an explicit, reviewable recovery path when a user manually deletes a
generated file but its durable ownership entry remains canonical.

# Scope

- Detect ownership entries whose target file is absent.
- Present the orphan and its recorded hash, generator, and timestamps.
- Offer explicit restore or ownership-release remediation without guessing.
- Preserve proposal review and trusted authorization for canonical ownership
  changes.
- Document why registry refresh does not delete durable ownership.

# Out of scope

- Automatically mutating `system/generated-ownership.json` during scan.
- Treating disposable registry state as ownership authority.
- Reconstructing missing generated content without a reviewed source.

# Acceptance criteria

- Orphaned ownership is visible with deterministic diagnostics.
- The user can explicitly choose a safe remediation path.
- No scan, startup, or ingestion action silently removes durable ownership.

# Relevant decisions and policy

- DD-035: generated ownership is durable authorization state.
- DD-080: Obsidian uses one digest-bound composite acceptance.
- DD-081: ingestion refuses orphaned ownership before draft publication.
- DD-082: orphan reconciliation is explicit, proposal-backed, and recoverable.
- `docs/safety-and-ownership.md`: generated ownership cannot be inferred away.

# Implementation record

- Added deterministic, read-only orphan diagnostics with the recorded raw hash,
  generator identity/version, creation/update timestamps, and restore guidance.
- Added the schema-v2 `release_generated_ownership` operation, bound to every
  reviewed ownership field and valid only while the target remains absent.
- Integrated manifest-only release with proposal preflight, application-time race
  checks, atomic ownership staging, rollback, recovery journals, and GitHub-style
  manifest diffs.
- Added bridge methods for listing orphans and creating high-risk release drafts;
  neither method accepts or applies a proposal.
- Added an Obsidian **Ownership recovery** workspace with explicit restore guidance
  and **Create release proposal**. Canonical release still requires the ordinary
  trusted **Accept changes** confirmation.
- Documented that registry refresh, startup, status, and ingestion never repair or
  delete durable ownership.

# Validation record

- Full Python suite with importlib collection: 1,423 passed. The one Unix-socket
  case blocked by the filesystem sandbox passed separately outside the sandbox.
- Focused proposal state-machine and reconciliation suite: 34 passed.
- Obsidian TypeScript suite: 53 passed; production artifact checks: 2 passed.
- Task-scoped Ruff: passed.
- Strict mypy across the five changed core source modules: passed. The legacy
  bridge application retains its unrelated existing strict-mypy baseline errors.
- Obsidian production build, manual link validation, and `git diff --check`: passed.
