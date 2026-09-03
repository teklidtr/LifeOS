---
id: LIFEOS-1002
title: Implement the local desktop bridge for Obsidian
status: completed
phase: 10
depends_on:
  - LIFEOS-1000
  - LIFEOS-1001
risk: high
---

# Goal

Expose the typed LifeOS application boundary to the desktop Obsidian plugin over
the local transport selected by LIFEOS-1000, with predictable lifecycle,
versioning, cancellation, and failure behavior.

# Scope

- Implement protocol handshake and capability negotiation.
- Expose only allowlisted typed operations required by Phase 10.
- Add request IDs, idempotency keys, structured errors, and cancellation where
  an operation can be long-running.
- Implement process startup, graceful shutdown, crash detection, and restart
  semantics.
- Keep protocol output isolated from logs and human-readable diagnostics.
- Bind each connection to an explicit local actor identity without granting
  agent authority.
- Provide read-only health and version endpoints.
- Add bounded event notifications for invalidation and attention-state changes.
- Sanitize host paths and exception representations in user-facing errors.
- Include a reference client used by tests independently of Obsidian.

# Out of scope

- Obsidian UI.
- Internet-facing access.
- Cloud synchronization.
- Arbitrary Python execution.
- A generic filesystem API.
- Automatic approval of consequential proposals.

# Required invariants

- The bridge cannot access files outside the configured vault and runtime roots.
- Unknown methods and extra fields are rejected.
- A crashed or incompatible bridge cannot corrupt canonical Markdown.
- Read-only requests never trigger recovery, rebuilding, or mutation.
- Consequential operations continue to require the trusted authorization path.
- The bridge can be stopped without leaving an ambiguous write transaction.

# Required tests

- Handshake success and protocol-version mismatch.
- Unknown method, malformed payload, and extra-field rejection.
- Request cancellation and client disconnect during a read.
- Client disconnect during a write leaves a recoverable or completed state.
- Duplicate idempotent request is not applied twice.
- Bridge crash and restart preserve canonical state.
- Logs never appear in protocol frames.
- Actor identity cannot be overridden by request payload.

# Acceptance criteria

- A non-Obsidian reference client can perform all allowlisted Phase 10 actions.
- Transport behavior is deterministic and fully typed.
- Security boundaries match the architecture from LIFEOS-1000.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/bridge tests/facade tests/integration -q
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-002: Deterministic facts and semantic interpretation are separate
- DD-004: Proposal application is explicit
- DD-011: Read before write
- DD-033: SQLite disposability and rebuilding
