---
id: LIFEOS-1656
title: Reserve the canonical capture mutation lineage namespace
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1654
risk: medium
---

# Goal

Prevent ordinary capture creation or transition inputs from impersonating the reserved merge/split
lineage namespace and causing predictable idempotency collisions or recovery-required denial of
service.

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
- Internal merge/split preparation can still write its request-bound output and source markers.
- Existing canonical notes with reserved-looking text remain loadable and fail closed unless their
  complete mutation lineage reconciles.
- Focused capture, bridge, Ruff, mypy, and broad practical validation pass.

# Documentation impact

Status: required

- `docs/rich-capture-protocol.md`: document that capture-mutation lineage values are reserved for
  the Python transaction engine.
- `docs/rich-capture-architecture.md`: identify the internal lineage namespace and public boundary.

# Validation

```bash
.venv/bin/pytest -q tests/captures tests/bridge/test_capture_bridge.py
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: canonical Markdown remains authoritative and human-readable.
- DD-036: Python is the sole business-rule engine for Obsidian interactions.
- DD-038: retryable direct mutations use optimistic concurrency and idempotency keys.
- LIFEOS-1654: merge/split retries require complete bilateral canonical lineage proof.
