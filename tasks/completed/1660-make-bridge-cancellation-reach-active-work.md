---
id: LIFEOS-1660
title: Make bridge cancellation reach active work
status: completed
phase: hardening
depends_on:
  - LIFEOS-1002
  - LIFEOS-1408
risk: high
---

# Goal

Make cancellation control frames reach the intended active operation and report a
truthful outcome while preserving serialized canonical mutations and safe recovery.

# Problem and evidence

`src/lifeos/bridge/server.py:23` reads the next frame only after synchronous
`dispatch` returns at line 36. A queued cancellation therefore cannot be consumed
while an operation runs. In `src/lifeos/bridge/application.py:3014`, `request.cancel` only
adds an ID to `_cancelled`; repository search found no consumer of that set.

Retrieval dispatch (lines 339-431) does not forward the already available
`CancellationToken` from `src/lifeos/retrieval/contracts.py` to token-capable
index/search/grounding services. The plugin's
`packages/obsidian-plugin/src/stdio-bridge-client.ts:95` generates IDs privately and
returns a Promise, so ordinary callers lack a correlated cancellation handle.

An event-blocked reproduction using the real server and application showed that the
work completed and emitted a successful response before the queued cancel response;
no token was forwarded. The later response still claimed
`{"cancelled": "work"}`.

# Scope

- Track active request IDs and cooperative cancellation signals; process control
  frames while work runs without introducing unrestricted parallel dispatch.
- Wire existing token-capable retrieval, indexing, and conversation paths.
- Audit `capture.enrichment.run/cancel` in `src/lifeos/bridge/application.py` and
  `src/lifeos/captures/processing.py`: currently cancellation updates stored job state without
  a bridge-supplied token reaching active enrichment.
- Expose safe frontend request correlation if needed while preserving existing
  Promise-based callers and strict protocol schemas.
- Define before-start, active, completed, unknown, repeated, and mismatched-ID
  outcomes; cancellation acknowledgement must not falsely claim completed work
  was interrupted.

# Out of scope

- A general job scheduler or unlimited concurrent canonical writers.
- Forcefully interrupting canonical transactions mid-commit or bypassing recovery.
- Changing provider selection, retrieval policy, actor authority, or capture
  lifecycle semantics unrelated to cancellation.

# Acceptance criteria

- A real transport test with event-blocked work processes targeted cancellation
  before work completes; the matching operation observes the signal and reports
  cancelled/interrupted truthfully. Unrelated work and later health requests work.
- Tests cover cancellation before start, during work, after completion, duplicate
  and unknown IDs, disconnect/shutdown, cleanup, and interleaved progress frames.
- Cancellation preserves the readable active index and valid resumable staging.
- Canonical mutations remain serialized and either finish their authorized commit
  or follow existing recovery rules; actor binding, idempotency, privacy context,
  and protocol-only stdout remain intact.
- Preserve the documented capture behavior: a cancelled enrichment job may leave
  its capture in `processing` until explicit retry or transition.
- Frontend request-correlation changes have TypeScript regressions and compatible
  existing call shapes.

# Documentation impact

Status: required

- `docs/obsidian-desktop-architecture.md`: document control-frame handling, request
  identity, process lifecycle, and safe cancellation/write concurrency semantics.
- `docs/semantic-retrieval-conversation-architecture.md`: align Performance and
  recovery with actual cancellation/checkpoint behavior.
- `docs/user-manual/13-rich-capture.md`: keep cancellation outcomes and the retained
  `processing` lifecycle caveat explicit; review other affected user controls.

# Validation

```bash
rtk .venv/bin/pytest -q tests/bridge tests/retrieval tests/conversations tests/captures
rtk npm --prefix packages/obsidian-plugin test
rtk npm --prefix packages/obsidian-plugin run typecheck
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk .venv/bin/python scripts/validate_manual_links.py
rtk git diff --check
```

Local validation on 2026-09-02:

- Bridge, retrieval, conversation, and capture suites passed, including real
  event-blocked transport cancellation, queued/active/completed outcome coverage,
  shutdown/disconnect cleanup, progress-frame interleaving, and capture processing.
- Obsidian plugin tests passed: 55 tests. TypeScript type checking passed.
- Ruff passed for `src` and `tests`; mypy passed for all 213 source files.
- The full isolated macOS pytest suite passed from a neutral sibling temporary
  root. An initial `/tmp` run reproduced only the three known macOS fixture-path
  false positives caused by `/tmp` resolving through `/private`; no production
  failure remained in the neutral rerun.
- Manual links passed for all 19 chapters, and `git diff --check` passed.
- GitHub normal and security review checkpoints could not be requested locally
  because the `gh` executable is unavailable. Both remain required before merge.

# Relevant decisions

- `AGENTS.md`: public-surface security review and canonical mutation boundaries.
- DD-036 and DD-037: Python owns business rules; a vault-scoped STDIO process has a
  strict versioned protocol.
- DD-038: observed hashes and idempotency protect direct UI mutations.
- DD-066: optional providers expose timeout, cancellation, and bounded-batch contracts.
- LIFEOS-1002 and LIFEOS-1408 already require cancellation/disconnect behavior;
  LIFEOS-1403 provides existing index interruption behavior to preserve.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `xhigh`.
- **Reason for the recommendation:** Transport concurrency, cooperative interruption,
  frontend correlation, and transaction safety interact across Python and TypeScript.
  The main risk is subtle lifecycle behavior, not the size of the cancellation handler.
