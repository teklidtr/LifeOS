---
id: LIFEOS-1000
title: Define the Obsidian-native daily interaction architecture
status: completed
phase: 10
depends_on:
  - LIFEOS-113
  - LIFEOS-907
risk: high
---

# Goal

Define the desktop-first architecture that makes Obsidian the primary LifeOS
interface while preserving the existing Python core as the only implementation
of business rules, validation, authorization, and canonical Markdown mutation.

# User outcome

A user should be able to live in Obsidian for normal daily work. The CLI remains
a debugging, automation, recovery, and test interface rather than the expected
human workflow.

# Scope

- Decide and document the plugin-to-Python integration model.
- Prefer a local, desktop-only process boundary with no remotely exposed
  unauthenticated endpoint.
- Define a versioned request, response, notification, and error envelope.
- Define service discovery, startup, shutdown, restart, and health-check
  behavior.
- Define capability negotiation so older plugins fail clearly against newer
  engines and vice versa.
- Define the trust boundary for read-only actions, direct user-authorized
  mutations, and consequential proposal actions.
- Define which state is canonical Markdown, durable authorization state,
  disposable runtime state, and ephemeral UI state.
- Define how stale reads and concurrent Obsidian edits are detected before a
  write.
- Define the initial plugin directory layout, build system, test layers, and
  release artifacts.
- Define desktop support and the deliberately reduced mobile story.
- Add accepted design decisions and update `docs/architecture.md` and
  `docs/roadmap.md` where necessary.

# Required design questions

- Does the plugin launch a long-lived LifeOS child process over JSON-RPC/STDIO,
  or connect to an opt-in local daemon? Document the selected default and why.
- How does the plugin locate the Python environment and repository package?
- How are duplicate engine processes prevented?
- How are actor identity and interactive authorization bound to the local user?
- How are protocol logs kept separate from STDIO transport bytes?
- Which operations may be retried safely, and how are idempotency keys handled?
- How does the UI represent `stale`, `blocked`, `corrupt`, `unsupported`, and
  `unavailable` results without flattening them into a generic error toast?
- How does the design preserve direct Markdown usability when the plugin is
  disabled or uninstalled?

# Out of scope

- Building the plugin UI.
- Implementing daily capture or task mutations.
- Mobile parity.
- Cloud sync, remote accounts, or multi-user collaboration.
- A general public HTTP API.
- Porting Python business logic to TypeScript.

# Required invariants

- Obsidian is the primary interaction surface, not a second source of truth.
- The plugin does not reimplement planner, study, proposal, recovery, or status
  semantics.
- Every canonical write uses typed Python services and stale-write protection.
- Uninstalling the plugin leaves a valid, fully readable Markdown vault.
- External agents cannot inherit the user interface's authorization implicitly.
- Protocol and UI state are disposable and rebuildable.
- The architecture remains testable without launching the full Obsidian app.

# Required deliverables

- One or more accepted design decisions.
- A protocol contract with example request, response, notification, and error
  messages.
- A component and trust-boundary diagram.
- A failure-mode table covering missing Python, crashed bridge, stale file,
  blocked recovery, incompatible protocol, and denied authorization.
- A proposed repository layout for Python bridge code and the TypeScript plugin.
- A sequenced implementation plan aligned with LIFEOS-1001 through LIFEOS-1012.

# Acceptance criteria

- The selected architecture allows ordinary daily use without terminal commands.
- The transport is local-only by default and has a documented threat model.
- Business logic has exactly one authoritative implementation in Python.
- Canonical, durable, derived, and ephemeral state boundaries are explicit.
- Every downstream Phase 10 task can rely on stable interface contracts.
- Internal Markdown links and diagrams validate.

# Validation commands

```bash
git diff --check
python -m pytest tests/project -q
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-004: Proposal application is explicit
- DD-007: Native Obsidian references first
- DD-021: Adaptive planning, not conventional task management
- DD-033: SQLite disposability and rebuilding
