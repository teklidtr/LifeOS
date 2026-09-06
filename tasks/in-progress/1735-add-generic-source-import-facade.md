---
id: LIFEOS-1735
title: Add generic source import and extraction facade
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-113
  - LIFEOS-1608
risk: high
---

# Goal

Extend the existing provider-independent typed facade with generic source-ingress operations so an
agent or other adapter can preserve and inspect arbitrary user-supplied regular files without a
file-type-specific LifeOS API such as `resume_import`, `asset_import`, or `salary_import`.

Reuse the existing Rich Capture attachment, hashing, deduplication, manifest, privacy, extraction,
and recovery machinery. This task adds an agent-safe facade over that machinery; it does not create
another source store or another canonical file format.

# Scope

- Add typed facade request/result models and descriptors for the generic source workflow, using the
  `source.*` namespace:
  - `source.import`: preserve one regular file as canonical source material through the existing
    capture/attachment storage contract and return stable LifeOS references rather than exposing
    storage internals.
  - `source.inspect`: inspect bounded canonical metadata, attachment integrity, processing state,
    privacy state, and available local processing for an already imported source.
  - `source.extract`: run or retrieve the existing deterministic/local extraction path when an
    extractor is available, while preserving explicit `unavailable`/unsupported states.
- Compose `CaptureArtifactService`, `AttachmentStore`, capture processing/extraction, and their
  existing contracts behind the facade rather than duplicating their business logic.
- Classify the facade effects consistently with the existing `ToolEffect` model: importing
  canonical source material is a canonical capture; inspection is read-only; rebuildable local
  extraction remains derived rather than a new source of truth.
- Preserve the existing Rich Capture model of canonical Markdown capture records, canonical
  attachment manifests, content-addressed original bytes, SHA-256 identity, duplicate reuse,
  lineage, and integrity checks.
- Accept only regular-file ingress through an explicitly trusted adapter boundary. Absolute host
  paths are invocation inputs only and must never become canonical vault state or appear in
  ordinary facade results.
- Keep privacy/sensitive classification explicit at import and enforce existing protected-scope
  rules before imported content or extracted text can be disclosed outside the allowed local
  boundary.
- Return enough stable references for a later agent-composed proposal to cite the imported source
  without requiring the caller to know `attachments/originals/`, manifest layout, hashes, or
  capture-path construction rules.
- Keep the facade provider-neutral. Semantic interpretation of the source remains an external-agent
  responsibility.

# Out of scope

- Resume-, finance-, property-, health-, tax-, or other domain-specific import functions.
- A new top-level vault folder or a second attachment/original-byte storage system.
- Automatic classification, summarization, wiki/profile creation, goal creation, or other semantic
  promotion after import.
- OCR, transcription, image understanding, or provider-backed enrichment not already implemented by
  Rich Capture.
- A network upload protocol or arbitrary remote access to the home-node host filesystem.
- Exposing these operations through MCP; that is owned by LIFEOS-1737.
- Changing Rich Capture lifecycle semantics, attachment deletion semantics, or proposal approval
  semantics.

# Required invariants

- Original imported bytes remain canonical, portable, content-addressed, and hash-verified through
  the existing attachment store.
- The facade wraps existing public/domain services and does not reimplement hashing, manifests,
  deduplication, extraction, privacy, locking, or recovery rules.
- Absolute machine paths never become canonical and are not returned as durable identity.
- Unsupported extraction remains explicit; no text or metadata is fabricated.
- Duplicate bytes reuse the existing canonical-original behavior; same-name different-content files
  remain distinct.
- The caller can describe intent, but LifeOS owns deterministic source identity and storage
  invariants.

# Acceptance criteria

- `source.import`, `source.inspect`, and `source.extract` are available as typed facade operations
  with strict request/result contracts and appropriate `ToolEffect` classifications.
- Importing representative PDF, text/TSV, XML, and unsupported binary fixtures uses the same generic
  API and requires no domain-specific branching in the facade contract.
- Source import creates/reuses the existing capture/attachment artifacts and does not introduce a
  parallel canonical source store.
- Exact-byte duplicate, same-name/different-content, changed-source-during-import, symlink,
  non-regular-file, missing-file, and unsafe-path cases preserve the existing fail-closed storage
  semantics.
- Facade results expose stable LifeOS references, content/media metadata, integrity/processing
  status, and privacy state without leaking absolute source paths or requiring callers to calculate
  hashes or construct attachment paths.
- Local extraction uses the existing deterministic extractor implementation and returns explicit
  unavailable/unsupported outcomes when appropriate.
- Protected/sensitive sources cannot expose source content or extracted text through a caller mode
  that existing privacy policy would deny.
- Focused facade and capture tests plus the broad cross-cutting regression suite pass.

# Documentation impact

Status: required

- `docs/architecture.md`: document generic source ingress as a typed-facade composition over Rich
  Capture rather than a new storage subsystem.
- `docs/rich-capture-architecture.md`: document the adapter/facade reuse boundary and distinguish
  generic source import from the existing Rich Capture user metaphor.

# Validation commands

```bash
uv run pytest -q tests/facade tests/captures
uv run pytest -q tests/bridge tests/mcp tests/integration
uv run pytest -q
uv run ruff check .
uv run mypy src
python scripts/validate_tasks.py
python scripts/validate_manual_links.py
```

Because this task changes a public facade, canonical file ingress, privacy handling, and filesystem
trust boundaries, run the broadest practical local pytest suite before pushing.

# Relevant design decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-003: Durable proposal mode.
- DD-017: Original sources remain immutable.
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine.
- DD-074 through DD-078: Rich Capture canonical artifacts, original-byte handling, processing,
  privacy, and recovery contracts.
- LIFEOS-113: the typed facade is provider-independent, wraps existing services, and hides raw
  filesystem/SQLite implementation details from agents and adapters.
- Rich Capture Architecture.
