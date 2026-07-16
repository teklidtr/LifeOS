---
id: LIFEOS-908
title: Decompose proposal application and recovery state machine
status: completed
phase: hardening
depends_on:
  - LIFEOS-112.3
risk: high
---

# Goal

Reduce the complexity of proposal application and recovery orchestration without
changing their safety contract, persisted journal schema, or observable
behavior.

# Discovered issue

Static complexity inspection identifies several oversized functions in the
proposal path, including `_apply_proposal_locked` with exceptionally high
cyclomatic complexity. The function coordinates validation, staging, journal
phases, canonical publication, ownership updates, proposal commit, rollback,
fault injection, and recovery classification. Keeping these concerns in one
control-flow graph makes future safety changes difficult to review and increases
the chance of an untested transition.

# Scope

- Add characterization tests for every existing journal phase, operation type,
  rollback outcome, fault checkpoint, and public error classification.
- Define explicit immutable application context and phase-result types.
- Extract validation, transaction preparation, target staging, target
  installation, ownership installation, proposal commit, completion, and
  ordinary-exception rollback into focused functions.
- Make legal phase transitions explicit and centrally validated.
- Preserve the recovery journal schema and deterministic serialization unless a
  separately reviewed migration is required.
- Preserve lock ownership and unresolved-transaction blocking.
- Preserve creation, replacement, and managed-block operation semantics.
- Preserve idempotent restart recovery and sanitized facade/MCP errors.
- Reduce complexity to reviewable thresholds with local, meaningful exception
  handling rather than broad wrappers.
- Keep fault-injection hooks at semantically equivalent boundaries.

# Out of scope

- Adding new proposal operation types.
- Changing approval or authorization policy.
- Claiming full machine power-loss durability.
- Replacing Git-tracked proposals with another authority.
- Combining this refactor with CLI, parser, or export cleanup.

# Required invariants

- A proposal is never marked applied before targets and ownership are installed.
- Ownership never claims absent or mismatched canonical content.
- Interrupted application remains discoverable and recoverable.
- New application refuses unresolved recovery state.
- Ordinary exceptions restore the documented original state or preserve an
  explicit recoverable transaction.
- Recovery remains idempotent.
- SQLite remains disposable and non-authoritative.

# Required tests

- Characterization matrix for all current operation and journal phase pairs.
- Every existing deterministic fault checkpoint before and after refactor.
- Multi-target failure after each installed target.
- Ownership and proposal-commit boundary failures.
- Roll-forward and rollback restart paths.
- Concurrent apply and recovery lock behavior.
- Corrupt and unavailable journal-state classification.
- Public facade and MCP error sanitization remains unchanged.
- Journal bytes for equivalent scenarios remain unchanged.

# Acceptance criteria

- `_apply_proposal_locked` becomes a small orchestration function whose phase
  transitions can be read sequentially.
- Extracted functions have explicit inputs, outputs, and narrow exceptions.
- Existing application and recovery tests remain green without weakened
  assertions.
- New characterization tests prove behavior and persisted state compatibility.
- Static complexity is substantially reduced in the proposal application path.
- No proposal safety boundary or authorization rule changes.

# Validation commands

```bash
pytest tests/proposals/test_application.py tests/proposals/test_recovery.py tests/test_recovery_io.py tests/facade tests/mcp tests/integration
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-003: Durable proposal mode
- DD-004: Proposal application is explicit
- DD-009: Managed blocks
- DD-031: Git-tracked proposals and stable layout
- DD-032: Typed JSON patches
- DD-033: SQLite disposability and rebuilding
- DD-034: Proposal validation
- DD-035: Durable generated ownership
