---
id: LIFEOS-1705
title: Build the derived Personal Model read model
status: completed
phase: 17
depends_on:
  - LIFEOS-1701
  - LIFEOS-1702
  - LIFEOS-1704
risk: medium
---

# Goal

Provide one inspectable view of tracked working hypotheses without creating another canonical semantic authority.

# Scope

- Build a rebuildable Personal Model index under `.lifeos/`.
- Index canonical patterns by stable ID, status, confidence, review reasons, evidence freshness, origin, and review due state.
- Produce a typed read model for active hypotheses, seeds, needs-review items, archived items, and evidence-health diagnostics.
- Preserve individual pattern IDs and canonical source links.
- Rebuild entirely from canonical Markdown.

# Out of scope

- Writing `profile/personal-model.md`.
- Generating a personality narrative.
- Hidden universal scores.
- Modifying patterns.
- Planner ranking changes.

# Required invariants

- Deleting `.lifeos/` Personal Model state loses no canonical knowledge.
- Every read-model item traces to canonical Markdown.
- Ordering is deterministic.
- Malformed patterns surface diagnostics rather than appearing healthy.

# Acceptance criteria

- Personal Model state is fully rebuildable.
- Empty, mixed-status, malformed, changed-evidence, duplicate-ID, and delete/rebuild cases are covered.
- No aggregate narrative becomes authoritative.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: the Phase 17 architecture already defines `.lifeos/personal-model/` as a deterministic, disposable aggregate with no semantic authority; LIFEOS-1705 implements that existing contract without changing it.
- `docs/architecture.md`: the existing Evidence-backed Personal Model layer already states the canonical-pattern versus rebuildable-read-model boundary; LIFEOS-1705 preserves that layer.
- `docs/personal-model-read-model.md`: records the concrete LIFEOS-1705 typed fields, diagnostics, evidence-health, freshness, publication, rebuild, and privacy contract.
- `docs/user-manual/personal-pattern-review-triggers.md`: explains canonical patterns versus the derived model, evidence-health states, malformed/duplicate diagnostics, and delete/rebuild behavior.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-001
- DD-008
- DD-013
- DD-033
- DD-039
- DD-061

# Validation evidence

- PR #45 fast-check workflow run `33848638284` passed on implementation/docs head `b93b8ae918b9afb6f8569e53ef8e98e7cca1f6ac`, including documentation-impact validation, manual-link validation, Ruff, mypy, Python compilation, pytest collection, and repository contract smoke tests.
- PR #45 full-validation workflow run `33848720069` passed on the same implementation/docs head: all four full pytest shards and aggregate `full-test` passed, and `docker-setup-e2e` passed the clean-room/MCP gate, home-node service-container gate, and ARM64 home-node image build.
- Focused tests cover empty and mixed-status models, malformed declared patterns, duplicate stable IDs, changed evidence without advancing reviewed hashes, deterministic recipe freshness, and deletion/rebuild of `.lifeos/personal-model/` with identical serialized output at a fixed evaluation time.
- The architecture files named by the task already contained the durable derived-state/layer decisions from LIFEOS-1700. LIFEOS-1705 did not redefine those decisions; the concrete implementation contract is documented in `docs/personal-model-read-model.md`, and user-facing behavior is documented in the Personal Pattern review-trigger manual page.
- An exact local checkout could not be obtained because the execution environment could not resolve `github.com`; this is an environment limitation rather than a validation pass. Consequently the task-listed local `git diff --check` command could not be executed directly. The closest practical substitute was the GitHub master-to-branch compare and PR patch/scope audit; no visible whitespace-error finding was observed.
- Code-review/Codex review and security review were explicitly skipped by the repository owner for this task. Full validation and merge-readiness checks were not waived.
