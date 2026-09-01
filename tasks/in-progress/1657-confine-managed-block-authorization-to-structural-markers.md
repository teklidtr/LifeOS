---
id: LIFEOS-1657
title: Confine managed-block authorization to structural markers
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-007
  - LIFEOS-104
  - LIFEOS-1302
  - LIFEOS-1405
  - LIFEOS-1501
  - LIFEOS-1601
risk: high
---

# Goal

Prevent marker-looking text inside Markdown code examples from being treated as an authorized
managed block or from bridging to a real marker and deleting human-owned content during refresh,
migration, proposal application, or artifact reconstruction.

# Scope

- Define one fail-closed structural grammar for managed markers: markers are authoritative only on
  unindented lines outside valid Markdown fenced code blocks.
- Recognize top-level CommonMark fence openers and closers with bounded indentation, matching fence
  characters and lengths, valid backtick info strings, and whitespace-only closing suffixes.
- Expose offset- or line-bound managed-block boundaries from the shared Markdown parser so mutation
  consumers can replace, extract, or remove the exact parsed block without a second DOTALL regex.
- Route proposal validation/application/snapshots, review artifacts and migration, daily review
  refresh, rich captures and manifests, knowledge conversations, and personal experiments through
  the shared structural boundary.
- Route retrieval and ingestion fence-sensitive heading scans through the same fence-state helper.
- Add adversarial regressions for backtick and tilde fences, false closers, longer fences,
  four-space and tab-indented examples, list-nested examples, fake-start-to-real-end bridging, and
  unchanged human bytes on rejected mutations.
- Audit the repository for remaining raw managed-marker replacement or extraction regexes.

# Out of scope

- Implementing a complete CommonMark block/container parser.
- Authorizing managed blocks nested inside lists, block quotes, indented code, or fenced code.
- Changing managed-marker names or the documented generated marker format.
- Changing proposal approval, optimistic concurrency, artifact schemas, or canonical ownership.
- Opportunistic refactors of artifact rendering or Markdown frontmatter parsing.

# Acceptance criteria

- Fenced, indented, tab-indented, list-nested, and block-quoted marker examples never appear in
  `ParsedNote.managed_blocks` and never authorize a canonical mutation.
- A fence content line with a marker run plus non-whitespace suffix cannot close the fence; closing
  requires the opener character, at least its length, at most three leading spaces, and only spaces
  or tabs afterward.
- No raw regex can pair a fake marker in human-owned content with a real managed-block marker.
- Every canonical managed-block consumer selects exactly one structurally parsed block and fails
  closed on missing, duplicate, malformed, or ambiguous boundaries before writing.
- Rejected refresh, migration, and proposal operations leave the complete canonical target
  unchanged; successful operations preserve every byte outside the parsed managed block.
- Existing valid review, capture, manifest, conversation, experiment, proposal, retrieval, and
  ingestion behavior remains compatible.
- Focused subsystem tests, Ruff, mypy, and the broad practical pytest suite are run.

# Documentation impact

Status: none
Reason: This restores the existing documented rule that only valid explicit managed blocks are
agent-writable; it does not change the marker format, user workflow, or architecture contract.

# Validation

```bash
.venv/bin/pytest -q tests/markdown/test_parser.py tests/proposals/test_validation.py tests/proposals/test_application.py tests/proposals/test_review_snapshot.py
.venv/bin/pytest -q tests/reviews/test_artifact.py tests/reviews/test_migration.py tests/daily/test_service.py
.venv/bin/pytest -q tests/captures/test_artifact.py tests/conversations/test_artifact.py tests/experiments/test_artifact.py
.venv/bin/pytest -q tests/retrieval/test_chunking_index.py tests/ingestion/test_proposals.py
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: canonical Markdown remains authoritative.
- DD-002: deterministic code enforces mutation boundaries.
- DD-003 and DD-004: consequential edits require durable proposals and explicit deterministic
  application.
- DD-009: agents may modify only content inside valid explicit managed blocks.
- DD-011 and DD-012: current targets are read and preservation checks are scripted before writes.
- DD-038: direct canonical writes retain optimistic concurrency and idempotency protections.
- `docs/safety-and-ownership.md`: human-owned Markdown is not overwritten and managed content is
  replaceable only inside valid markers.
