---
id: LIFEOS-1657
title: Confine managed-block authorization to structural markers
status: completed
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

# Review handoff

The user requested that this partially completed task be finished first, followed by
backlog capture only. Implementation was committed as `dfdeb02` and the completed task
state as `fe4eb1c`. No remaining backlog task was promoted or implemented during the
handoff. The full-suite macOS limitation above is now recorded in LIFEOS-1659.

The remaining verified findings are preserved below in severity order. LIFEOS-1655 and
LIFEOS-1656 already existed and were enriched rather than duplicated; LIFEOS-1658 was
created during the managed-marker work and its contract was corrected to preserve the
actual top-level checkbox renderer. LIFEOS-1659 through LIFEOS-1666 are new follow-ups.
LIFEOS-1667 records the historical status-metadata inconsistency found during handoff validation.
Within a severity group, this is suggested triage order, not a new dependency rule.

| Risk | Backlog task | Purpose | Recommended model / reasoning effort |
|---|---|---|---|
| Critical | [LIFEOS-1655](../backlog/1655-confine-derived-publication-recovery-paths.md) | Confine persisted publication recovery paths and destructive cleanup. | `gpt-5.6-sol` / `xhigh` |
| High | [LIFEOS-1658](../backlog/1658-confine-review-item-decision-markers-to-structural-lines.md) | Restrict review decision/proposal-reference authorization to real rendered items. | `gpt-5.6-sol` / `high` |
| High | [LIFEOS-1659](../backlog/1659-restore-safe-macos-recovery-readiness.md) | Restore supported macOS recovery diagnostics without weakening Git/filesystem safety. | `gpt-5.6-sol` / `xhigh` |
| High | [LIFEOS-1660](../backlog/1660-make-bridge-cancellation-reach-active-work.md) | Make cancellation reach active bridge work while preserving safe mutation serialization. | `gpt-5.6-sol` / `xhigh` |
| High | [LIFEOS-1664](../backlog/1664-clean-up-failed-owned-lock-acquisition.md) | Avoid abandoned locks after failed or partial token initialization. | `gpt-5.6-sol` / `high` |
| Medium | [LIFEOS-1656](../backlog/1656-reserve-capture-mutation-lineage-namespace.md) | Prevent public capture inputs from impersonating reserved mutation lineage. | `gpt-5.6-terra` / `high` |
| Medium | [LIFEOS-1661](../backlog/1661-use-canonical-generated-ownership-in-status-lint.md) | Diagnose generated-file integrity using the canonical ownership manifest. | `gpt-5.6-luna` / `medium` |
| Medium | [LIFEOS-1662](../backlog/1662-report-unhashable-frontmatter-keys-as-parse-findings.md) | Convert composite YAML-key crashes into structured parser findings. | `gpt-5.6-luna` / `medium` |
| Medium | [LIFEOS-1663](../backlog/1663-resume-source-guarded-capture-and-experiment-index-rebuilds.md) | Resume the two write-only derived-index checkpoints with source validation. | `gpt-5.6-sol` / `high` |
| Medium | [LIFEOS-1666](../backlog/1666-preserve-human-markdown-in-metadata-only-updates.md) | Preserve existing body bytes in remaining metadata writers and proposal builders. | `gpt-5.6-terra` / `high` |
| Low | [LIFEOS-1665](../backlog/1665-align-registry-schema-documentation.md) | Correct stale version-3 registry documentation to the shipped version-4 contract. | `gpt-5.6-luna` / `medium` |
| Low | [LIFEOS-1667](../backlog/1667-reconcile-historical-task-status-metadata.md) | Reconcile 32 historical completed-task status fields without changing completion evidence. | `gpt-5.6-luna` / `low` |

Each backlog task contains its reproduction/current behavior, affected code and tests,
source-of-authority references, preservation boundaries, acceptance criteria, validation,
documentation impact, dependencies, and a task-specific model rationale. The capture and
experiment checkpoint findings are grouped because they share the write-only checkpoint
root cause; they are explicitly separate from canonical capture-mutation recovery.

Resolved or unconfirmed findings were not duplicated as new work:

- Attachment path confinement: LIFEOS-1652, `f0a4ec4`.
- Persisted capture enum validation: `f4894ca`.
- Capture retrieval exclusions: `52d85b0`.
- Provider preview retrieval-policy enforcement: LIFEOS-1653, `df08168`.
- Transactional, stale-safe capture merge/split: LIFEOS-1654, `4619804`.
- Structural managed-block authorization and exact managed-refresh preservation:
  this task, `dfdeb02`.
- The former whole-file image-metadata allocation is already resolved by LIFEOS-1652:
  `LocalExtractionService._image_metadata` in `src/lifeos/captures/extraction.py` reads
  only 32 header bytes. Streaming integrity hashing is separate and intentional.
- No separate custom research-delimiter task was created: inspection did not establish
  a concrete remaining contract violation. The invalid standalone-review-marker assumption
  was corrected in LIFEOS-1658 rather than promoted into a new requirement. That task
  changes decision/proposal-reference authorization, not separate draft-creation authority.
- Temporary-directory/protected-path and parent-Git-discovery fixture artifacts were
  avoided by the documented test isolation; they were not attributed to this implementation.

Model recommendations use options actually exposed by the Codex environment on
2026-09-02: `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`, with the listed available
reasoning efforts. OpenAI Docs was used to check the
[official model-selection guidance](https://developers.openai.com/api/docs/guides/latest-model)
and the [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol),
[Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), and
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) model references.
The task-specific recommendations are engineering judgments based on risk, ambiguity,
compatibility, and exploration needs, not promises about future account availability.
Recheck availability in a future session; do not invent an unavailable configuration.

No implementation-critical review context is intentionally left only in the conversation.
Future work should use these tasks and current authoritative repository sources, not
conversation recollection. Unrelated local `.serena/` state was left untouched.

Handoff validation checked unique task IDs, required task sections, documentation-impact
declarations, available model/effort combinations, local file references, relative handoff
links, and empty ready/in-progress queues. Dependency IDs resolve to task files already
under `tasks/completed/`, as required by the promotion rule. Three referenced historical
dependencies have stale frontmatter among the 32 mismatches now recorded in LIFEOS-1667;
their metadata was not silently changed or presented as consistent. Manual links in all
19 chapters and `git diff --check` passed. No source/test/plugin changes were made after
the LIFEOS-1657 implementation commit.
