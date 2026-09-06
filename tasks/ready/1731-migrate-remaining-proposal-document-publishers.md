---
id: LIFEOS-1731
title: Migrate remaining proposal-document producers to the shared publisher
status: ready
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

- [ ] Every named producer uses the shared publisher; equivalent local directory/write/cleanup bodies are deleted.
- [ ] The ingestion path actually used at runtime and its ordinary core persistence path cannot select different file-publication implementations.
- [ ] A repository-wide publication inventory records each remaining direct write as an intentional different operation or resolves it through the publisher. No equivalent producer is left on a parallel implementation.
- [ ] Existing successful lifecycle, duplicate/error, provenance, identity, immutable-review, and filesystem failure tests continue to pass with equivalent behavioral assertions.
- [ ] Shared-API additions, if any, remain narrowly necessary; domain callbacks, arbitrary document registries, and feature-flag matrices are not introduced.
- [ ] Record net implementation/concept deletion, counting thin error adapters and retained tests honestly.

# Documentation impact

Status: required
- `docs/architecture.md`: update publisher adoption/ownership to include all migrated feature families and identify the remaining ingestion composition boundary.
- Review relevant planning, review, ownership, and ingestion documentation for any implementation references; public behavior remains unchanged.

# Validation

```bash
uv run pytest -q tests/copilot tests/planning_feedback tests/reviews tests/ownership tests/ingestion tests/proposals
uv run pytest -q tests/captures tests/conversations tests/experiments tests/patterns tests/facade tests/mcp tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Exercise failed publication and duplicate handling in each migrated family, not only generic publisher tests. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-003, DD-004, DD-031, DD-034, DD-046, and DD-051: proposal layout, validation, and planning/feedback authority.
- DD-081, DD-083, DD-090, and DD-092: ingestion ownership, review history, identity, and batch verification.

# Implementation size and sequencing

Medium: six bounded consumer migrations onto an established primitive. Depends on LIFEOS-1730. Complete before LIFEOS-1732 so ingestion composition work starts with one publication implementation.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** Once the shared boundary is validated, adoption is primarily bounded coding and caller migration. Terra is sufficient; high reasoning remains appropriate for error compatibility, verification ordering, and cleanup ownership across the six consumers.
