---
id: LIFEOS-1625
title: Harden proposal recovery and bridge errors
status: completed
phase: 16
depends_on:
  - LIFEOS-1624
risk: high
---

# Goal

Prevent a retained terminal proposal-application journal from blocking later
writes after the user legitimately changes canonical files, and keep expected
proposal failures inside the JSON-RPC error boundary instead of crashing the
Obsidian bridge and exposing a traceback.

# Scope

- Treat a structurally valid `complete` recovery journal as terminal cleanup
  state without revalidating canonical targets that may have changed after the
  completed application.
- Preserve fail-closed canonical-state verification for every incomplete
  recovery phase.
- Map expected proposal service failures to typed bridge errors.
- Add a final STDIO server error boundary so one unexpected request failure
  cannot terminate the bridge or leak an implementation traceback to the UI.
- Document the terminal-journal cleanup and bridge error behavior.

# Out of scope

- Weakening proposal target hashes, ownership validation, or interrupted
  transaction recovery.
- Automatically repairing durable generated-ownership entries.
- Automatically retrying or applying a proposal after a failure.
- Changing the proposal lifecycle or MCP ingestion behavior.

# Acceptance criteria

- A valid retained `complete` journal is cleaned even when its previously
  committed canonical files have subsequently changed or been removed.
- Incomplete journals still fail closed when canonical state does not match the
  recorded recovery phase.
- Proposal execution failures return one typed JSON-RPC error and the bridge
  remains available for the next request.
- Error frames expose a concise public message, not a Python traceback.
- Focused recovery and bridge tests, full Python validation, documentation
  links, and diff checks pass.

# Validation

```bash
uv run pytest -q tests/proposals/test_recovery_orchestration.py tests/bridge/test_bridge.py tests/desktop/test_proposals.py
uv run ruff check src tests
uv run mypy src
uv run pytest -q
python scripts/validate_manual_links.py
git diff --check
```

# Relevant decisions

- DD-004: Proposal application is explicit.
- DD-034: Proposal validation remains deterministic.
- DD-035: Generated ownership remains durable authorization state.
- DD-036: Python owns proposal and recovery semantics.
- DD-037: The bridge uses versioned JSON-RPC over STDIO.
- DD-080: Composite acceptance stops at the last durable state on failure.

# Implementation record

- Changed recovery orchestration so a structurally validated `complete` journal
  is cleaned as terminal state without comparing canonical content that may
  have legitimately changed after the completed commit.
- Kept canonical phase verification unchanged for every incomplete journal.
- Mapped proposal service `ValueError` failures to typed `proposal_invalid`
  JSON-RPC errors.
- Added a final STDIO request boundary that returns a redacted
  `internal_error`, keeps the bridge process alive, and never serializes the
  traceback or local paths.
- Documented terminal journal cleanup and request error containment.
- Cleaned the affected vault's stale completed journal through the corrected
  recovery service after copying it to a temporary, recoverable backup.
- Recorded ownership-aware ingestion and orphaned ownership remediation as
  separate backlog tasks LIFEOS-1626 and LIFEOS-1627.

# Validation record

- Focused recovery, bridge, and desktop proposal tests: 30 passed.
- Focused Ruff checks for changed Python files: passed.
- Full Python suite with importlib collection: 1407 passed; the one Unix-socket
  integrity case blocked by the filesystem sandbox passed separately outside
  the sandbox.
- Manual links and `git diff --check`: passed.
- Repository-wide Ruff and mypy remain blocked by pre-existing baseline errors
  already tracked by LIFEOS-1616; changed-file Ruff checks are clean.
