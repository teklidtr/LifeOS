---
id: LIFEOS-1654
title: Make capture merge and split atomic and stale safe
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1602
  - LIFEOS-1605
  - LIFEOS-1606
risk: high
---

# Goal

Make merge and split one stale-guarded, recoverable canonical mutation so a failure, retry, or
concurrent Obsidian edit cannot archive newer human content, leave a partial result, duplicate
outputs, or weaken capture privacy policy.

# Scope

- Bind merge application to a server-computed fingerprint over the exact source paths, source
  hashes, and derived preview fields; reject duplicate sources and tampered previews.
- Validate every merge source and split group, source lifecycle transition, and output document
  before the first canonical write.
- Pre-render complete output and archived-source Markdown, including annotations and lineage,
  without direct unguarded `Path` writes.
- Apply all output creations and source archive replacements through one descriptor-pinned,
  stale-checked file-set transaction with durable runtime recovery state.
- Recover or fail closed on an interrupted capture transaction before starting another merge or
  split, and preserve external edits when rollback cannot prove ownership of installed bytes.
- Add idempotency keys for retryable bridge mutations and reject reuse with different inputs.
- Propagate the most restrictive source privacy scope, sensitivity, and every retrieval exclusion
  to merged output; preserve all of those fields on split output.
- Add focused service, bridge, recovery, and plugin regressions for the affected invariants.

# Out of scope

- Routing capture-local mutations through the proposal approval lifecycle.
- Changing capture or attachment schema versions.
- Changing merge selection heuristics or treating similarity as proof of duplication.
- Adding delete semantics for attachment originals or omitted split attachments.
- Generalizing every LifeOS canonical mutation onto the new file-set transaction boundary.

# Acceptance criteria

- A merge fails before mutation when its preview is stale, malformed, source-duplicated, or altered
  after the server generated it.
- Split rejects no groups, empty groups, duplicate attachment assignments, unknown attachments,
  and a source that cannot transition to archived, without writing an output.
- A source edit racing either operation is never overwritten or silently archived; a handled
  failure at any publication boundary leaves the pre-operation canonical state intact.
- Interrupted operations are deterministically recovered before another merge or split, or expose
  an explicit recovery-required error without overwriting ambiguous canonical state.
- A retry with the same idempotency key and identical input returns the original result paths;
  reuse with different input fails and no duplicate lineage event is written.
- Merge and split preserve human annotations, attachment/link references, lineage, restrictive
  privacy/sensitivity, and all four exclusion flags.
- No transaction staging, backup, or journal artifact remains after a successful operation or
  successful recovery.
- Existing bridge response shapes remain compatible apart from additive preview and optional
  request fields.
- Focused tests, plugin tests, Ruff, mypy, manual-link validation, and the broad practical pytest
  suite are run.

# Documentation impact

Status: required

- `docs/rich-capture-architecture.md`: document the merge/split transaction and recovery boundary.
- `docs/rich-capture-protocol.md`: document bound previews and idempotent retry inputs.
- `docs/user-manual/13-rich-capture.md`: document all-or-nothing behavior, recovery, validation,
  and monotonic privacy propagation.

# Validation

```bash
.venv/bin/pytest -q tests/captures/test_storage_processing.py tests/captures/test_merge_split_transaction.py tests/bridge/test_capture_bridge.py
npm --prefix packages/obsidian-plugin test -- --run rich-capture-workspace.test.ts
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/python scripts/validate_manual_links.py
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: Markdown remains canonical and human-readable.
- DD-038: retryable direct UI mutations use observed hashes and idempotency keys.
- DD-074: capture Markdown and original attachment bytes are canonical evidence.
- DD-076: protected and excluded capture content remains default deny.
- `docs/rich-capture-protocol.md`: merge application requires an unchanged preview fingerprint.
- `docs/user-manual/13-rich-capture.md`: merge fails if a source changes after preview.
