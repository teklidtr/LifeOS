---
id: LIFEOS-1627
title: Reconcile orphaned generated ownership
status: backlog
phase: 16
depends_on:
  - LIFEOS-1626
risk: high
---

# Goal

Provide an explicit, reviewable recovery path when a user manually deletes a
generated file but its durable ownership entry remains canonical.

# Scope

- Detect ownership entries whose target file is absent.
- Present the orphan and its recorded hash, generator, and timestamps.
- Offer explicit restore or ownership-release remediation without guessing.
- Preserve proposal review and trusted authorization for canonical ownership
  changes.
- Document why registry refresh does not delete durable ownership.

# Out of scope

- Automatically mutating `system/generated-ownership.json` during scan.
- Treating disposable registry state as ownership authority.
- Reconstructing missing generated content without a reviewed source.

# Acceptance criteria

- Orphaned ownership is visible with deterministic diagnostics.
- The user can explicitly choose a safe remediation path.
- No scan, startup, or ingestion action silently removes durable ownership.
