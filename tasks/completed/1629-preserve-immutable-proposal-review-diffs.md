---
id: LIFEOS-1629
title: Preserve immutable proposal review diffs
status: completed
phase: 16
depends_on:
  - LIFEOS-1627
risk: high
---

# Goal

Keep the exact operation diffs reviewed with a proposal available after its
targets or ownership manifest have changed.

# Scope

- Define a strict, versioned immutable review-diff snapshot inside each new
  proposal directory.
- Bind the snapshot to proposal identity, ordered typed operations, and the
  lifecycle review digest.
- Create the snapshot before draft publication from the same bounded operation
  inputs and current target state.
- Render proposal history from the snapshot instead of current vault state.
- Preserve read compatibility for legacy proposals without a snapshot.
- Detect malformed, mismatched, or changed snapshots and fail closed for new
  lifecycle transitions.

# Out of scope

- Reconstructing exact historical diffs for legacy proposals that never stored
  the required before-state.
- Replacing typed operations with raw unified diffs.
- Using SQLite or Git history as the only proposal review history.

# Acceptance criteria

- A new applied proposal keeps the same reviewed diff after its target changes,
  moves, or disappears.
- `create_generated_file`, `patch_human_file`, `replace_generated_file`,
  `replace_managed_block`, and `release_generated_ownership` snapshots are
  deterministic and ordered.
- Snapshot tampering or operation mismatch is visible and cannot retain the
  original review authorization.
- Existing proposals without snapshots still load and use an explicit legacy
  preview fallback.

# Relevant decisions and policy

- DD-031: proposals are durable Git-tracked history.
- DD-032: typed operations remain authoritative.
- DD-034: approval never bypasses validation.
- DD-080: one confirmation is bound to the exact reviewed digest.
- `docs/safety-and-ownership.md`: consequential changes remain inspectable and
  reviewable.

# Implementation

- Added canonical `review.json` snapshots for every proposal publisher.
- Bound snapshots to proposal loading, lifecycle review digests and locked
  application source verification.
- Made the desktop bridge and Obsidian proposal view snapshot-first with an
  explicit legacy live-preview fallback.
- Preserved typed operations as the only application authority.

# Validation

- `1429` Python tests passed with importlib collection mode, including focused
  proposal, lifecycle, application, facade, desktop and ownership coverage.
- `53` Obsidian plugin tests passed.
- Production plugin build and artifact tests passed.
- Strict mypy passed for the snapshot, loader, lifecycle and desktop proposal
  modules.
