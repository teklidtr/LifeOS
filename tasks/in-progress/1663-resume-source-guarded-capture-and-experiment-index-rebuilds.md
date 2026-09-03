---
id: LIFEOS-1663
title: Resume source-guarded capture and experiment index rebuilds
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-1503
  - LIFEOS-1507
  - LIFEOS-1607
risk: medium
---

# Goal

Make interrupted capture and experiment index rebuilds actually resume bounded work, without
treating stale runtime checkpoints as authority over the current canonical Markdown.

# Problem and current behavior

Both rebuilders write progress files but never read them on the next invocation:

- `src/lifeos/captures/recovery.py`: `rebuild_capture_index` initializes empty entries and identity
  maps on every call and writes `captures/rebuild-checkpoint.json` beneath the configured runtime
  directory. `_all_capture_artifacts` reads and parses all captures before the checkpoint loop.
- `src/lifeos/experiments/history.py`: `rebuild_experiment_index` similarly starts over and writes
  `experiments/rebuild-checkpoint.json`, including a `processed` count and `last_path` that are
  never consumed.

The review reproduced this with three valid canonical artifacts per subsystem and two successive
calls using `batch_size=1, interrupt_after=1`: each call reported the same first item and one item
processed. Capture discovery also reparsed all three captures before either interruption. A later
uninterrupted rebuild can succeed, but repeated bounded interruptions make no forward progress.
This contradicts `docs/rich-capture-recovery.md`'s bounded/resumable rebuild contract and the
checkpointed experiment-recovery contract in `docs/personal-experiment-architecture.md`.

These are **derived index rebuild checkpoints**, not the canonical merge/split transaction
recovery records under `.lifeos/capture-mutations/` implemented by LIFEOS-1654.

# Scope

- Define and implement a minimal resumable checkpoint contract for each index, including enough
  source identity/version and partial-result information to continue safely.
- Reuse verified progress only when it still matches current canonical sources. Detect changed,
  added, moved, deleted, duplicated, malformed, or unsupported artifacts; invalidate/restart stale
  work or report a safe recovery condition rather than silently publishing stale entries.
- Bound actual source-processing work, not just the number of already-parsed entries reported by
  the progress loop. Make discovery versus processing costs explicit and testable.
- Keep checkpoint contents disposable, schema-validated, and confined to the configured runtime
  directory. Missing, corrupt, truncated, or unsupported checkpoint data must permit a safe fresh
  rebuild without canonical repair.
- Audit the two rebuild entry points and their bridge callers for report-shape compatibility.
  Share a helper only if it simplifies the common invariant; do not create a general job framework.

# Out of scope

- Capture merge/split mutation journals, transaction recovery, or canonical artifact repair.
- New migration formats, a new publication subsystem, or changes to canonical schemas.
- Making checkpoint contents or derived indexes authoritative over Markdown or attachments.
- Unrelated enrichment, scheduling, index-query, or gallery functionality.

# Acceptance criteria

- Successive bounded interrupted invocations on unchanged sources advance beyond prior completed
  work and eventually produce the same complete entries, ordering, and diagnostics as a fresh
  uninterrupted rebuild. Instrumented processing counts prove that progress is real.
- Edits, additions, moves, deletions, and duplicate IDs between invocations never publish an index
  that falsely represents the current source set. Tests cover the selected invalidation/restart
  policy, including changes to artifacts processed before interruption.
- Malformed/unsupported artifacts, moved paths, duplicate identity, and existing recovery-audit
  diagnostics retain their current meaning. Neither resumed nor fresh rebuilds rewrite canonical
  notes, annotations, original attachments, or source hashes.
- Removing all runtime state still permits a complete rebuild. Corrupt or incompatible checkpoint
  data fails safely without trapping the user in a permanently unresumable state.
- Existing index schemas, sorted output, bridge/report shapes, and complete-index loading remain
  compatible unless an explicitly documented runtime-only migration is necessary.
- Subsystem regressions and broad local validation pass, with independent environment limitations
  recorded rather than hidden.

# Regression coverage

- Extend `tests/captures/test_privacy_migration_recovery.py` and
  `tests/experiments/test_analysis_history.py`. Existing tests exercise interruption followed by a
  fresh/unrestricted rebuild; they do not prove that repeated bounded runs consume a checkpoint.
- Cover empty sources, interruption at a batch boundary, completion cleanup, repeated interruption,
  malformed/truncated checkpoint JSON, unknown checkpoint schema, and the source changes above.
- Verify byte-for-byte canonical preservation and unchanged supported capture/experiment bridge
  recovery responses. Preserve attachment-integrity and privacy behavior of the surrounding audit.

# Documentation impact

Status: required

- `docs/rich-capture-recovery.md`: document actual checkpoint resume, source validation, and safe
  invalidation/restart behavior, distinguishing derived indexes from mutation recovery records.
- `docs/personal-experiment-architecture.md`: clarify the checkpointed index-recovery contract.
- `docs/user-manual/13-rich-capture.md`: update the recovery instructions and interruption states.
  Review experiment recovery guidance in `docs/user-manual/` for the same user-visible behavior.
- Review `docs/design-decisions.md` DD-073 and DD-078; preserve their existing source-guarded and
  disposable-state boundaries rather than weakening them to match the defective implementation.

# Validation

```bash
rtk .venv/bin/pytest -q tests/captures/test_privacy_migration_recovery.py tests/experiments/test_analysis_history.py
rtk .venv/bin/pytest -q tests/captures tests/experiments tests/bridge
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk .venv/bin/python scripts/validate_manual_links.py
rtk git diff --check
```

# Relevant decisions

- `AGENTS.md`: canonical Markdown, disposable derived state, scoped implementation, and broad
  validation for persistence/recovery changes.
- `docs/architecture.md`: Personal experiments and Rich capture boundaries.
- DD-001, DD-013, and DD-033: canonical source authority and rebuildable deterministic indexes.
- DD-073: experiment runtime recovery and source-guarded migration.
- DD-078: attachment identity and disposable capture-derived state.
- Completed LIFEOS-1503, LIFEOS-1507, and LIFEOS-1607 establish these rebuild surfaces.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `high`.
- **Reason for the recommendation:** Resumption must reconcile partial state with a changing
  canonical source set across two indexers while preserving subtle diagnostics and report shapes.
  The difficult work is recovery design and invariant testing, not writing checkpoint JSON.
