---
id: LIFEOS-1301
title: Add versioned review artifact contracts
status: backlog
phase: 13
depends_on:
  - LIFEOS-1300
risk: high
---

# Goal

Create validated Python and TypeScript contracts for canonical review artifacts, phases, sections, items, decisions, prompts, answers, lifecycle, and provenance.

# Scope

- Define schema versions and compatibility diagnostics.
- Model stable review, phase, section, item, decision, answer, source, and proposal references.
- Preserve unknown values and partial completion.
- Add parsers, serializers, structural validation, and cross-language parity tests.

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
