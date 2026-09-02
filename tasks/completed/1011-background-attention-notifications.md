---
id: LIFEOS-1011
title: Deliver attention notifications while Obsidian is closed
status: completed
phase: 10
depends_on:
  - LIFEOS-1002
  - LIFEOS-1007
risk: high
---

# Goal

Add an opt-in local scheduler and operating-system notification adapter so
important attention items can surface even when Obsidian is not running, while
keeping detection deterministic and privacy-preserving.

# Scope

- Implement an optional background LifeOS service using the architecture chosen
  in LIFEOS-1000.
- Schedule morning, evening, weekly, and condition-based attention evaluations.
- Support quiet hours, timezone, per-routine frequency, snooze, and disable.
- Deliver concise notifications that open the relevant Obsidian LifeOS view.
- Keep notification text privacy-aware by default.
- Store scheduler configuration in an explicit, human-inspectable location.
- Prevent duplicate notifications for the same stable attention item.
- Reconcile notification actions with the plugin when it next connects.
- Add platform adapters for the initially supported desktop operating systems.
- Provide install, uninstall, start, stop, and status behavior without requiring
  the user to manually run a foreground terminal process each day.

# Out of scope

- Mobile push notifications.
- Cloud messaging.
- LLM-generated notification text.
- Reading email or calendar.
- Marking tasks complete from a lock-screen notification in v1.

# Required invariants

- Background evaluation uses the same attention engine as Obsidian.
- Notifications never reveal private note content unless the user opts in.
- Disabled routines and quiet hours are honored.
- The scheduler does not mutate canonical Markdown merely because time passed.
- A missed schedule is handled deterministically after sleep or reboot.
- Service installation is explicit and reversible.

# Required tests

- Morning, evening, weekly, and condition-based schedules.
- Timezone changes, DST, sleep, reboot, and clock rollback.
- Duplicate suppression and snooze.
- Obsidian closed, opened, and reconnected scenarios.
- Disabled routine and quiet-hours enforcement.
- Notification click opens the correct dashboard context.
- Service crash does not corrupt attention preferences or canonical state.
- Platform adapter contract tests.

# Acceptance criteria

- A forgotten evening reconciliation can be surfaced without prompting an
  agent or keeping Obsidian open.
- Delivery remains local, opt-in, and deterministic.
- The service is installable and removable through documented UI or setup flow.
- Full tests and platform-specific smoke checks pass.

# Validation commands

```bash
pytest tests/attention tests/scheduler tests/integration -q
npm --prefix packages/obsidian-plugin test
pytest -q
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-027: Skipped tasks trigger diagnosis
- DD-033: SQLite disposability and rebuilding
