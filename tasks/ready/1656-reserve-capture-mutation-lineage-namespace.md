---
id: LIFEOS-1656
title: Reserve the canonical capture mutation lineage namespace
status: ready
phase: hardening
depends_on:
  - LIFEOS-1654
risk: medium
---

# Goal

Prevent ordinary capture creation or transition inputs from impersonating the reserved merge/split
lineage namespace and causing predictable idempotency collisions or recovery-required denial of
service.

# Problem and current behavior

`CaptureArtifactService.create` in `src/lifeos/captures/artifact.py` accepts arbitrary
`source_entry_point` text, and the public bridge forwards it from `capture.create` in
`src/lifeos/bridge/application.py`. The public `transition` method and bridge likewise
accept arbitrary lifecycle reasons.

`src/lifeos/captures/processing.py` reserves the following internal lineage values:

- `_mutation_marker`: `capture-mutation:<operation>:<key_hash>:<request_hash>:<index>:<total>`.
- `_source_mutation_marker`:
  `capture-mutation-source:<operation>:<key_hash>:<request_hash>:<index>:<total>:<result_ids>`.
- Source provenance kind `capture-mutation` and archive reasons `merged into <id>` or
  `split into <id>, ...`.

`_existing_mutation_results` scans persisted captures for matching mutation key hashes.
During review, a public create request could plant a syntactically reserved six-field
`source_entry_point`, causing a later merge/split using the matching key to fail with
`idempotency_conflict` or `recovery_required`. LIFEOS-1654's full bilateral source/result
proof prevents a forged successful mutation, but does not prevent this collision/denial
of service. The task is to reserve public inputs, not to trust runtime receipts more.

# Scope

- Define one internal validator for reserved capture mutation marker and archive-lineage prefixes.
- Reject reserved lineage values at public service, bridge, and plugin-facing capture creation or
  transition boundaries while keeping the internal transactional preparation path available.
- Preserve canonical Markdown authority: manually authored reserved markers remain readable but
  never count as completed mutations without the full bilateral lineage proof.
- Add service and bridge regressions for exact prefixes, prefix variants, and ordinary source and
  lifecycle text.

# Out of scope

- Authenticating or signing canonical Markdown.
- Changing the merge/split transaction or idempotency-key format.
- Reclassifying existing non-mutation provenance values.

# Acceptance criteria

- Public callers cannot create new canonical capture metadata or lifecycle reasons in the reserved
  capture-mutation namespace.
- Reserved-input rejection happens before any canonical write, produces a stable typed capture
  error, and is exercised through both the service and bridge. Ordinary text that merely mentions
  mutation concepts is not over-broadly rejected.
- Internal merge/split preparation can still write its request-bound output and source markers.
- `prepare_create` and `prepare_transition` remain usable by the internal transactional path;
  repeated merge/split requests still reconcile their complete canonical lineage after runtime loss.
- Existing canonical notes with reserved-looking text remain loadable and fail closed unless their
  complete mutation lineage reconciles.
- Focused capture, bridge, Ruff, mypy, and broad practical validation pass.

# Documentation impact

Status: required

- `docs/rich-capture-protocol.md`: document that capture-mutation lineage values are reserved for
  the Python transaction engine.
- `docs/rich-capture-architecture.md`: identify the internal lineage namespace and public boundary.
- Review `docs/user-manual/13-rich-capture.md` for any user-facing validation/error guidance affected
  by rejecting previously accepted reserved inputs; do not suggest editing lineage to bypass checks.

# Validation

```bash
rtk .venv/bin/pytest -q tests/captures tests/bridge/test_capture_bridge.py
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- `AGENTS.md`: canonical Markdown authority, deterministic mutation, and scope control.
- DD-001: canonical Markdown remains authoritative and human-readable.
- DD-036: Python is the sole business-rule engine for Obsidian interactions.
- DD-038: retryable direct mutations use optimistic concurrency and idempotency keys.
- LIFEOS-1654: merge/split retries require complete bilateral canonical lineage proof.

Extend `tests/captures/test_merge_split_transaction.py`, `tests/captures/test_artifact.py`, and
`tests/bridge/test_capture_bridge.py`. Include exact reserved prefixes, malformed reserved variants,
ordinary source/reason strings, canonical-byte preservation on rejection, and valid internal retry
and recovery behavior. Do not reject manually edited historical notes at the generic parser.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** The fix has a well-defined public-input boundary and strong
  transaction tests to build on, but requires careful separation of public writes, internal lineage
  preparation, and historical Markdown compatibility.
