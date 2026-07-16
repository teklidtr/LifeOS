---
id: LIFEOS-907
title: Typed status diagnostics and narrow failure mapping
status: completed
phase: hardening
depends_on: []
risk: medium
---

# Goal

Make `lifeos status` preserve partial read-only availability without masking
programming defects or collapsing subsystem failures into generic exceptions.

# Discovered issue

`src/lifeos/status.py` catches broad `Exception` around multiple subsystem
checks, and the CLI boundary also has broad failure handling. This makes status
appear resilient, but it can hide defects such as `TypeError`, `AttributeError`,
or invariant violations and loses the subsystem-specific reason a check is
unavailable or corrupt.

# Scope

- Define typed result models for configuration, vault, registry, proposals,
  ownership, recovery, graph, and export status checks.
- Distinguish healthy, stale, unavailable, corrupt, blocked, and unsupported
  states.
- Map only documented filesystem, configuration, schema, and domain exceptions.
- Let unexpected programming exceptions fail loudly during development and
  tests.
- Preserve sanitized user-facing messages without leaking host paths or raw
  tracebacks.
- Include stable diagnostic codes and subsystem names in JSON output.
- Keep text output concise while showing partial results and next actions.
- Add one aggregation layer that cannot accidentally mark skipped checks as
  healthy.

# Out of scope

- Automatic repair from the status command.
- Swallowing unknown exceptions to preserve a zero exit code.
- Adding network health checks.
- Replacing subsystem-specific validation logic.

# Required tests

- Expected filesystem unavailability produces a typed partial result.
- Corrupt registry, proposal, ownership, graph, and export state are
  distinguishable.
- Programmer errors such as injected `TypeError` are not swallowed.
- JSON output contains stable codes, subsystem, state, and sanitized detail.
- Text output preserves all failing subsystem names.
- Exit-code policy is tested for healthy, degraded, blocked, and unexpected
  failure states.
- A failure in one optional subsystem does not prevent independent read-only
  checks from completing.
- Host absolute paths and raw exception representations are not exposed.

# Acceptance criteria

- Production status aggregation contains no broad `except Exception` or
  `except BaseException` handlers.
- Every expected failure maps to one documented typed status.
- Unknown defects remain visible to tests and callers.
- Text and JSON status outputs agree on subsystem state and severity.
- Partial status is useful without becoming falsely reassuring.

# Validation commands

```bash
pytest tests/test_status.py tests/cli
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-005: Status and confidence
- DD-011: Read before write
- DD-033: SQLite disposability and rebuilding
- DD-035: Durable generated ownership
