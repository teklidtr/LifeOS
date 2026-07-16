---
id: LIFEOS-112
title: Crash recovery
status: completed
depends_on: []
---

# Objective
Coordinate deterministic recovery for interrupted consequential proposal
application without relying on SQLite or MCP-specific logic.

LIFEOS-112.1 through LIFEOS-112.3 guarantee deterministic recovery from
ordinary exceptions and process interruption.

Full sudden-power-loss durability requiring file fsync, directory fsync, and
platform-specific persistence ordering is not claimed by these tasks.

# Child tasks
- LIFEOS-112.1
- LIFEOS-112.2
- LIFEOS-112.3

# Completion evidence

All three child tasks are complete:
* LIFEOS-112.1 established deterministic journals, discovery, and locking.
* LIFEOS-112.2 integrated crash-safe journaling into proposal application.
* LIFEOS-112.3 added deterministic recovery orchestration and sanitized
  external error boundaries.

The completed recovery system covers ordinary exceptions and process
interruption. It does not claim sudden-power-loss durability.
