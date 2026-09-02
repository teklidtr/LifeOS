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

# Implementation notes

- `ManagedBlock` now carries exact offsets relative to `ParsedNote.body`; its existing line and
  content attributes remain available. The parser, retrieval chunking, and ingestion heading scans
  share the same fence-state grammar.
- `replace_managed_block` validates that a replacement is one complete structural block before
  splicing it. This also rejects an early closing marker followed by a fence that hides the intended
  closing marker. The non-validating `splice_managed_block` is used only for extraction/removal.
- Proposal preflight, application, and review snapshots use the same exact content span. Replacement
  text remains verbatim: no implicit newline is added. Preflight fixtures that previously depended
  on an inapplicable, newline-normalized candidate now supply the required newline explicitly.
- Artifact updates retain the current body and replace only its parsed managed span. Existing human
  body bytes, location, blank lines, trailing spaces, CRLF endings, and fenced marker examples remain
  unchanged. Authorized metadata updates remain separate from the body. Review migration insertions
  also retain the existing bytes on both sides of the insertion.
- The independent review-item fingerprint scanner is not part of this implementation; its separate
  authorization defect is captured in LIFEOS-1658.

# Validation evidence

Validated locally on macOS on 2026-09-02:

- All four focused validation groups above, including the final added regressions: **239 passed**.
- Ruff: passed for `src` and `tests`.
- Mypy: passed for all 213 source files.
- Full pytest suite after the final material edit: **2,054 passed, 54 failed, 12 skipped**. All 54
  failures are in `tests/cli/test_doctor_recovery*.py`, caused by the existing macOS pinned Git
  directory limitation (`_recovery_readiness_impl._pinned_fd_path`: "Platform cannot expose a
  pinned Git object directory safely"). No recovery implementation was changed by this task.
  This independent issue was also observed during LIFEOS-1654 and remains unresolved; it is not
  presented as a green full-repository result.
- The full run used a disposable directory under ignored `.pytest_cache/`, outside the sandbox for
  Unix-socket tests, with `GIT_CEILING_DIRECTORIES` set to the test parent. This avoids unrelated
  fixtures mistaking macOS `/private/` temporary paths for protected vault scope or inheriting this
  repository's Git root. An initial unisolated cache-directory run had one additional scanner
  fixture failure; it passed once Git discovery was isolated. Every affected-subsystem test is
  included in the final full run and passed.
- Repository-wide text and AST searches found no remaining raw managed-marker DOTALL replacement
  regex, duplicate fence-state implementation, stale removed helper reference, or affected
  monkeypatch/return-shape dependency. The existing application error wording is preserved.
- Final independent local invariant review found no blocking defects in the consolidated parser
  and writer boundary. `git diff --check` passed.
- Documentation impact was reviewed against the vision, architecture, accepted decisions, and
  ownership policy: this restores the already documented boundary, so no user or data-contract
  documentation requires a behavior change.
