---
id: LIFEOS-1300
title: Define first-class review artifact architecture
status: completed
phase: 13
depends_on:
  - LIFEOS-1009
  - LIFEOS-1210
risk: high
---

# Goal

Define the canonical boundaries, lifecycle, identity, migration path, and Obsidian-native interaction model for daily and weekly review artifacts.

# Scope

- Audit the Phase 10 wizard, runtime progress, journal check-ins, weekly review sections, attention engine, proposal lifecycle, and goal-plan replanning integration.
- Define one daily artifact with morning and evening phases and one weekly artifact per ISO week.
- Separate canonical review content, managed deterministic snapshots, human-owned reflection, proposal-backed external changes, and disposable UI caches.
- Define lifecycle, continuity, conflict handling, rebuild, migration, and removal behavior.
- Add design decisions, data-flow diagrams, failure modes, and a sequenced implementation map.

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
