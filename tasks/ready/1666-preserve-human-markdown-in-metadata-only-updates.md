---
id: LIFEOS-1666
title: Preserve human Markdown in metadata-only updates
status: ready
phase: hardening
depends_on:
  - LIFEOS-1657
risk: medium
---

# Goal

Preserve the exact existing Markdown body when a direct service operation or proposal builder
changes only frontmatter, and preserve the original body prefix when an authorized append occurs.

# Problem and current behavior

`_frontmatter_document` in `src/lifeos/daily/service.py` defaults to `preserve_body=False`. That
path removes leading newline characters, strips all trailing whitespace from the resulting
document, and forces one final newline. Several callers pass an existing human-authored body
while intending to change metadata only. A review reproduction with multiple leading blank
lines and trailing Markdown spaces changed the body even though no body edit was requested.

This can remove meaningful Markdown trailing spaces, alter human formatting, introduce unrelated
proposal diffs, and interfere with no-op detection. LIFEOS-1657 added a `preserve_body=True` path
for managed-block refreshes; it deliberately did not widen into the remaining metadata writers.
This task is the separate follow-up, not a reopening of managed-block authorization.

Confirmed existing-body call sites to inspect:

- `src/lifeos/daily/service.py`: `DailyInteractionService.quick_capture`'s existing-plan task
  branch, `update_checkin` for an existing journal, and `record_task_outcome`.
- `src/lifeos/study/session.py`: `StudySessionService._append_journal` when the journal exists.
- `src/lifeos/feedback/preferences.py`: `FeedbackControlService.correct_outcome`.
- `src/lifeos/reviews/decisions.py`: `create_review_proposal`.
- `src/lifeos/feedback/proposals.py`: `create_feedback_proposal`.
- `src/lifeos/copilot/proposals.py`: `create_copilot_plan_proposal`'s existing-goal update and
  `_conflict_operations`' existing-plan updates.
- `src/lifeos/copilot/replanning.py`: `create_replanning_proposal`.

`update_checkin` with an explicit note also calls `body.rstrip()` before appending the note;
simply changing its final render call would still trim the existing prefix on that branch.
Its no-note metadata-only branch is an unambiguous instance of the shared defect.

# Scope

- Audit every caller of the shared helper and distinguish formatting a newly created document
  from updating a previously read body. Opt existing-body paths into exact preservation using
  the existing helper rather than introducing another renderer or blindly changing its default.
- Keep intentionally requested body additions explicit and preserve the original prefix rather
  than normalizing it while appending. Do not broaden the content a direct write may change.
- Preserve existing body text both in proposal candidate patches and after authorized application;
  proposal-producing functions must not become direct canonical writers.
- Add exact-body regression coverage across the affected daily, study, feedback, review, and
  copilot paths, including any caller-specific preprocessing that otherwise defeats preservation.

# Out of scope

- Byte-preserving YAML/frontmatter formatting, a new frontmatter parser, or metadata-schema changes.
- Changes to managed-block selection, review item authorization, or the LIFEOS-1657 implementation.
- Reformatting newly created captures/journals/plans or unrelated generated text.
- Changing proposal approval, allowed metadata fields, stale-hash checks, or idempotency semantics.

# Acceptance criteria

- An existing note's body is byte-for-byte unchanged by metadata-only operations. Exact tests
  cover leading/trailing blank lines, spaces/tabs, Markdown hard-break spaces, CRLF body text,
  and a body without a final newline.
- An explicitly requested body append retains every original body byte as its prefix; only the
  authorized new content/separator is appended. Empty/no-note updates do not invent body edits.
- Requested metadata changes still occur, unrelated metadata/IDs retain their existing semantic
  preservation guarantees, and stale requests or rejected proposals leave canonical bytes intact.
- Proposal diffs contain no incidental body normalization. Existing no-op detection, expected
  hashes, review snapshots, idempotency, and proposal-only mutation boundaries remain compatible.
- New-document formatting remains unchanged. In particular, preserve the existing behavior of
  `quick_capture`'s new-note branch, `copilot.proposals._plan_document`, and new journal creation.
- Existing managed refresh callers already using `preserve_body=True` (or `not created`) continue
  to pass their LIFEOS-1657 regressions without a new rendering abstraction.

# Regression coverage

- `tests/daily/test_service.py`: task capture into an existing plan, check-ins with/without notes,
  and task outcomes; strengthen containment-only human-content assertions to exact preservation.
- `tests/study/test_session.py`: existing versus newly created journal behavior.
- `tests/planning_feedback/test_preferences.py` and
  `tests/planning_feedback/test_feedback_proposals.py`: corrections and proposal candidates.
- `tests/reviews/test_decisions.py`: metadata-only review proposal targets.
- `tests/copilot/test_copilot_proposals.py` and `tests/copilot/test_replanning.py`: existing goal,
  superseded/conflicting plan, and replanning proposal preservation.
- Exercise a representative full proposal build/review/application path, not only the render helper.

# Documentation impact

Status: none
Reason: This restores the existing human-owned-content preservation contract for metadata updates
and explicit appends. It changes neither supported user actions nor proposal/mutation authority,
and intentionally retains established formatting for newly created documents.

# Validation

```bash
rtk .venv/bin/pytest -q tests/daily/test_service.py tests/study/test_session.py
rtk .venv/bin/pytest -q tests/planning_feedback/test_preferences.py tests/planning_feedback/test_feedback_proposals.py tests/reviews/test_decisions.py
rtk .venv/bin/pytest -q tests/copilot/test_copilot_proposals.py tests/copilot/test_replanning.py
rtk .venv/bin/pytest -q tests/daily tests/study tests/planning_feedback tests/reviews tests/copilot tests/proposals
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

Before broad validation, search all `_frontmatter_document` callers, preserve_body uses, and any
changed monkeypatch/return/error seams as required by `AGENTS.md`'s consolidation safety rules.

# Relevant decisions

- `AGENTS.md`: human-owned content must not be silently rewritten; consequential changes remain
  proposals, and shared behavior changes require broad compatibility validation.
- `docs/architecture.md`: deterministic layer, proposal engine, daily/feedback, and copilot bounds.
- `docs/safety-and-ownership.md`: human-owned Markdown and preservation before canonical writes.
- DD-001, DD-009, DD-011, and DD-012: canonical Markdown, managed ownership, current targets, and
  scripted preservation checks.
- DD-038 and DD-039: stale-write/idempotency safety and canonical execution/correction history.
- Completed LIFEOS-1657: the exact-body helper path and managed-refresh compatibility baseline.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** The implementation direction is established, but separating
  existing-body updates from intentional creation/append behavior requires careful cross-module
  exploration and preservation of proposal, no-op, and concurrency semantics.
