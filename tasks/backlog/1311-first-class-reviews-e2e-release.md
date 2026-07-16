---
id: LIFEOS-1311
title: Validate and document first-class reviews
status: backlog
phase: 13
depends_on:
  - LIFEOS-1310
risk: high
---

# Goal

Ship end-to-end fixtures, release gates, documentation, removal guidance, and complete task/commit accounting.

# Scope

- Test sparse, typical, degraded, migrated, concurrent-edit, proposal, and long-history vaults.
- Validate bridge and TypeScript contract compatibility, performance budgets, manual links, and provider neutrality.
- Update roadmap, architecture, user manual, setup, troubleshooting, and release scripts.
- Confirm that deleting disposable state does not lose review progress.

# Out of scope

- Automatic interpretation of the user as a person.
- Automatic application of consequential changes outside a review artifact.
- Cloud accounts, collaboration, social comparison, or completion scoring.
- Replacing Obsidian with a command-only workflow.

# Required invariants

- Markdown remains canonical and readable without the plugin.
- Human-owned reflection is never overwritten by managed refresh.
- Missing evidence remains unknown rather than negative evidence.
- A review may be partial, intentionally skipped, reopened, or left incomplete.
- External canonical changes remain proposal-gated.
- Stable identities and optimistic concurrency prevent silent duplication or overwrite.
- Disposable runtime state is never the only home of review progress.

# Required tests

- Sparse and fully populated vaults.
- Partial completion, skip, reopen, resume, and concurrent edit.
- Managed refresh preserving human-owned content.
- Missing, malformed, stale, duplicate, and unsupported artifacts.
- Provider-neutral behavior without a configured model.
- Python and TypeScript contract parity where applicable.

# Acceptance criteria

- The capability is usable from Obsidian without terminal commands.
- Review artifacts remain useful as ordinary Markdown notes.
- Focused tests and relevant regression suites pass.
- Task status, architecture, and user documentation stay synchronized.

# Validation commands

```bash
pytest tests/reviews tests/daily tests/attention tests/integration -q
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run typecheck
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-011: Read before write
- DD-012: Preservation checks are scripted
- DD-030: Scope-local logs are generated views
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-038: Direct UI writes use optimistic concurrency and idempotency
- DD-041: Missing evidence is not negative evidence
- DD-052: Living replanning starts from current canonical state
