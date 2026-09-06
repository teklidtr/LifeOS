---
id: LIFEOS-1731
title: Migrate remaining proposal-document producers to the shared publisher
status: completed
phase: hardening
depends_on:
  - LIFEOS-1730
risk: high
---

# Goal

Complete adoption of the narrow publisher so equivalent proposal-file publication is no longer implemented separately by planning, reviews, ownership reconciliation, and ingestion.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, repeated three-document writes occur in `copilot.proposals._publish`, `copilot.replanning._publish`, `feedback.proposals.create_feedback_proposal`, `reviews.decisions.create_review_proposal`, `ownership.reconciliation._publish_proposal`, and ingestion's `_persist_proposal_documents`/`_secure_persist_proposal_documents`. The ingestion public module replaces the core persistence function at import time. Revalidate these consumers after LIFEOS-1730.

# Scope

- Migrate the six named producer families in `src/lifeos/copilot/`, `feedback/proposals.py`, `reviews/decisions.py`, `ownership/reconciliation.py`, and `ingestion/{proposals,_proposals_core}.py` to the publisher delivered by LIFEOS-1730.
- Preserve thin feature-specific duplicate/error adapters, return values, and the point at which sources, targets, ownership, and review bytes are verified.
- Remove the old physical write/cleanup implementations, including the superseded ingestion core publication body. Route the currently active ingestion entry point through the publisher without redesigning its builder/import composition in this task.
- Audit all production writes of the three proposal documents for remaining equivalent creation paths. Route equivalent paths through the primitive; explicitly classify lifecycle edits or other distinct operations rather than incorrectly treating them as new-proposal publication.

# Out of scope

- Ingestion module substitution and ambient provenance removal (LIFEOS-1732), proposal application, feedback/review interpretation, or planning semantics.
- Broadening the publisher into an extensible persistence framework or changing the already migrated families except for a necessary shared-boundary compatibility fix.

# Required invariants

- Keep evidence fingerprints, duplicate detection, reviewed target identity/version, immutable review digests, feature-specific errors/messages, and proposal IDs/paths/statuses unchanged.
- Preserve all source/target prepublication checks, including multi-source re-verification and ingestion ownership classification; the publisher does not interpret evidence or infer permission.
- Preserve safe root handling, no-follow/descriptor ownership, write failure behavior, and cleanup limited to the failed attempt. Never remove existing proposal history.
- Retain direct API shapes and meaningful monkeypatch failure seams; audit changed helpers and migrate every known dependent test in the same change.

# Acceptance criteria

- [x] Every named producer uses the shared publisher; equivalent local directory/write/cleanup bodies are deleted.
- [x] The ingestion path actually used at runtime and its ordinary core persistence path cannot select different file-publication implementations.
- [x] A repository-wide publication inventory records each remaining direct write as an intentional different operation or resolves it through the publisher. No equivalent producer is left on a parallel implementation.
- [x] Existing successful lifecycle, duplicate/error, provenance, identity, immutable-review, and filesystem failure tests continue to pass with equivalent behavioral assertions.
- [x] Shared-API additions, if any, remain narrowly necessary; domain callbacks, arbitrary document registries, and feature-flag matrices are not introduced.
- [x] Record net implementation/concept deletion, counting thin error adapters and retained tests honestly.

# Documentation impact

Status: required

- Updated `docs/architecture.md` so the shared proposal publisher explicitly owns physical draft publication for goal-to-plan copilot, replanning, feedback, review-decision, ownership-reconciliation, and ingestion in addition to the families migrated by LIFEOS-1730.
- The architecture text keeps evidence, source/target, ownership, identity, and immutable-review verification feature-owned and records the remaining ingestion public-module/core composition boundary as LIFEOS-1732 work.
- Reviewed the relevant user-manual behavior and design-decision contracts. No user-manual or design-decision edit is required because proposal IDs, paths, lifecycle behavior, errors, review bytes, provenance, authorization, and user-facing workflows are unchanged; this task consolidates only the internal physical publication boundary.

# Implementation evidence

- `copilot.proposals`, `copilot.replanning`, `feedback.proposals`, `reviews.decisions`, and `ownership.reconciliation` now prepare their feature-owned bytes and call `lifeos.proposals.publication.publish_proposal_documents`, retaining thin feature-specific error adapters.
- Ingestion core now uses the same shared publisher. The public ingestion module no longer installs a second `_secure_persist_proposal_documents` implementation or replaces `_core._persist_proposal_documents` at import time, so ordinary core and active runtime persistence cannot diverge physically.
- Added the narrow `preflight_proposal_publication` shared seam only to preserve ingestion's established ordering: unsafe-root and duplicate checks occur before immutable review-snapshot construction. The publisher still has no domain callbacks, document registry, policy interpretation, or feature matrix.
- Failure seams were migrated to the actual shared filesystem boundary. Tests cover injected publication failure and duplicate handling across every migrated producer family, plus ingestion runtime/core identity.

## Publication inventory

Repository-wide review of production references to `proposal.md`, `patches.json`, `review.json`, and the secure writer found these remaining canonical-write classes:

1. `src/lifeos/proposals/publication.py` is the sole physical writer for initial three-document draft publication. It writes exactly `proposal.md`, `patches.json`, and `review.json` into an owned staging directory and publishes the completed directory without replacing existing history.
2. `src/lifeos/proposals/lifecycle.py` intentionally rewrites an existing proposal's `proposal.md` for explicit lifecycle/frontmatter transitions after re-reading and re-verifying proposal, patch, and immutable-review sources. This is an existing-proposal lifecycle mutation, not a parallel draft publisher.
3. `src/lifeos/proposals/migration.py` does not own another writer; legacy lifecycle migration delegates to the same lifecycle transition primitive, so its `proposal.md` mutation is the intentional lifecycle-migration case above.
4. `src/lifeos/proposals/application.py` treats `proposal.md`, `patches.json`, and `review.json` as verified application inputs and transactionally commits the approved proposal's lifecycle state; `src/lifeos/proposals/recovery_service.py` may restore/complete that `proposal.md` transaction from the recovery journal after interruption. These are application/recovery operations on an existing proposal, explicitly outside new-proposal publication. Neither provides an alternate `patches.json` or immutable `review.json` draft-publication path.

No equivalent producer remains with a local three-document directory/write/cleanup implementation.

## Deletion and size accounting

Conceptually, the change deletes the repeated physical publication/cleanup implementations in the five non-ingestion producer modules, the ingestion wrapper publisher, the ingestion core's former physical write body, and the import-time substitution that allowed runtime/core persistence to select different implementations. What remains at feature call sites is byte preparation plus thin compatibility/error translation.

The textual diff is intentionally not claimed as a line-count reduction. Ruff formatting of touched legacy files plus regression coverage makes the production diff net positive despite deleting duplicated publication concepts. Against starting master `4655975fbeae97319ac6c919b7b663bcdadc63eb`, the implementation commit `e0321435c79c3a9a30715edc9cdd63e093b88631` has production `src/` changes of 713 additions and 409 deletions (net +304), tests of 532 additions and 264 deletions (net +268), and 2 architecture-document additions. The consolidation win is one physical publication implementation rather than fewer textual lines.

# Validation

The local checkout attempt could not reach GitHub because the execution container could not resolve `github.com`. Per root `AGENTS.md`, the closest executable substitute was a clean GitHub-hosted Actions checkout with locked dependencies. The final bounded validation run `34024772103` on the implementation produced:

- focused publisher/adoption, ingestion-root hardening, and facade fault-seam coverage: **15 passed**;
- `uv run pytest -q tests/copilot tests/planning_feedback tests/reviews tests/ownership tests/ingestion tests/proposals`: **815 passed**;
- `uv run pytest -q tests/captures tests/conversations tests/experiments tests/patterns tests/facade tests/mcp tests/integration`: **667 passed**;
- `uv run pytest -q`: **2480 passed**;
- `uv run ruff check .`: passed;
- `uv run mypy src`: passed, 235 source files checked;
- `python scripts/validate_tasks.py`: passed;
- `git diff --check`: passed;
- Ruff format check across all 11 touched Python files: passed.

Repository-wide `uv run ruff format --check .` remains the pre-existing tracked LIFEOS-1734 baseline blocker. This change does not worsen it: after formatting the touched files, the reported debt improved from 267 files requiring formatting on master/LIFEOS-1730 to **257 files requiring formatting**. No duplicate follow-up task was created.

# Relevant design decisions

- DD-003, DD-004, DD-031, DD-034, DD-046, and DD-051: proposal layout, validation, and planning/feedback authority.
- DD-081, DD-083, DD-090, and DD-092: ingestion ownership, review history, identity, and batch verification.

# Implementation size and sequencing

Medium: six bounded consumer migrations onto an established primitive. Depends on LIFEOS-1730. Complete before LIFEOS-1732 so ingestion composition work starts with one publication implementation.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** Once the shared boundary is validated, adoption is primarily bounded coding and caller migration. Terra is sufficient; high reasoning remains appropriate for error compatibility, verification ordering, and cleanup ownership across the six consumers.

## Codex review fixes

Normal Codex review of head `d899c3bbf0c13528a8a5ba699f864150362310d0` identified three P2 compatibility/cleanup findings. They were batched into one invariant-focused fix:

- ingestion now explicitly rejects a `proposals_root` whose final component is not the canonical `proposals` directory, preventing a successful write to a different path than the returned path;
- the shared publisher records the identity of a newly created staging directory before opening it and removes that empty directory only when the still-present entry matches the owned identity after an open failure;
- all five migrated feature adapters preserve their former duplicate-publication `FileExistsError` detail while still translating through their existing feature-specific exception prefixes.

Post-review validation run `34025780821` produced **31 passed** for focused publisher/adoption/root-hardening coverage, **817 passed** for the task subsystem group, **667 passed** for the cross-subsystem group, and **2482 passed** for the full suite. `uv run ruff check .`, `uv run mypy src`, `python scripts/validate_tasks.py`, `git diff --check`, and touched-file Ruff formatting all passed. Repository-wide Ruff formatting remained at the tracked LIFEOS-1734 baseline of **257 files would be reformatted**.

### Second Codex review cleanup audit

Codex re-review of head `ff331e075b3454de2358b11717ce5f1217203d4c` found one additional P2 variant of the failed-attempt cleanup invariant: the new pre-open staging identity `stat` could fail immediately after `mkdir`. A broader early-exit audit showed that blindly removing the random staging name in this branch would weaken the ownership invariant because a concurrent replacement could be deleted. The final fix therefore treats a path-stat failure as recoverable when the staging directory can still be opened through the secure no-follow primitive: it binds ownership from the opened fd, re-verifies the directory entry, and continues publication. If the pre-open identity is unavailable and secure open also fails, it deliberately does not delete by name because ownership cannot be proven. Existing open-failure cleanup remains identity-gated when the pre-open identity was captured. A regression test injects a one-shot staging identity lookup failure and verifies successful publication with no orphan staging directory.

Post-fix validation run `34026971052` produced **32 passed** for focused publisher/adoption/root-hardening coverage, **818 passed** for the task subsystem group, **667 passed** for the cross-subsystem group, and **2483 passed** for the full suite. `uv run ruff check .`, `uv run mypy src`, `python scripts/validate_tasks.py`, `git diff --check`, and touched-file Ruff formatting all passed. Repository-wide Ruff formatting remained at **257 files would be reformatted**, matching the tracked LIFEOS-1734 branch baseline.
