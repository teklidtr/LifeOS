---
id: LIFEOS-107
title: SQLite indexing, dashboards, status, and CLI integration
status: completed
milestone: phase-2-proposal-engine
depends_on: [LIFEOS-106]
risk: low
affected_paths:
  - src/lifeos/registry/_migrations.py
  - src/lifeos/registry/proposals.py
  - src/lifeos/cli.py
  - src/lifeos/status.py
---

# Goal

Index all Git-tracked proposals into the disposable SQLite registry for fast dashboard queries, and integrate proposal visibility into the CLI `status` and `propose` commands.

# Scope

- Add a migration for `proposals` tables in `_migrations.py`.
- Implement a `register_proposals_scan()` method to load all proposals from disk and index their `id`, `status`, `created_at`, `updated_at`, and `title` into SQLite.
- Ensure the SQLite index is fully disposable and rebuildable from the filesystem upon every scan.
- Add `lifeos proposals list` (dashboard preview) to the CLI, querying the fast SQLite index.
- Update `lifeos status` to report proposal counts grouped by status (e.g., 2 pending, 1 approved).

# Out-of-Scope

- Do not change SQLite into the canonical source of truth for proposals. Deleting `registry.db` must never lose an approved proposal.
- Do not apply patches via CLI in this task (handled in e2e tests / next phase).

# Acceptance Criteria

1. SQLite table accurately mirrors the `proposals/` filesystem state after a registry scan.
2. `lifeos proposals list` effectively retrieves and displays pending and approved proposals.
3. `lifeos status` correctly outputs proposal statistics from the index.
4. Deleting `registry.db` and running a scan completely restores the proposal index without data loss.

# Validation Commands

```bash
pytest tests/registry/test_proposals_index.py
pytest tests/cli/test_proposals_cli.py
```

# Relevant Design Decisions

- SQLite is disposable, rebuildable query state and must not be the only home of proposal history.
- Generated dashboards may group proposals by status.

**Implementation completed.**

Delivered:
- proposal registry schema migration
- Git-tracked proposal indexing
- typed query service
- lifeos proposals list
- proposal lifecycle counts in lifeos status
- disposable registry rebuild verification

Canonical source:
- Git-tracked proposal Markdown

Derived state:
- SQLite registry

Final verification:
- 334 tests passed
- Ruff passed
- mypy passed
