---
id: LIFEOS-1632
title: Enable agent-directed compounding wiki evolution
status: completed
phase: 16
depends_on:
  - LIFEOS-1631
risk: high
---

# Goal

Let the external AI agent evolve durable wiki knowledge from each registered raw
source without forcing a universal taxonomy or a one-input/one-output shape.
LifeOS should constrain mutations, not semantic organization.

# Design principle

**Semantic policy is minimal; mutation policy is strict.**

The agent may decide that one source should produce no durable wiki change, one
change, or several coordinated changes. It may reuse existing notes and choose
or evolve folders under `wiki/` according to the knowledge already present.
LifeOS owns path safety, ownership checks, source verification, bounded operation
counts, immutable review artifacts, lifecycle authorization, atomic application,
and recovery.

# Scope

- Add read-only wiki discovery so the external MCP agent can search existing
  durable knowledge before choosing targets.
- Add one compounding ingestion contract that accepts a bounded set of generated
  page creations and ownership-aware exact-section updates in one atomic draft.
- Require a concise rationale for every proposed mutation so page selection is
  inspectable in review artifacts.
- Allow generated page targets anywhere under `wiki/`, including useful nested
  folders chosen by the agent from the current vault context.
- Safely create missing nested parent directories for approved generated wiki
  creates while still rejecting symlinks, escapes, missing `wiki/`, and
  non-generated creates.
- Keep the prior single-create, single-update, and two-operation compound tools as
  compatibility APIs, but stop instructing agents to prefer fixed page kinds.
- Treat `source/entity/concept/synthesis` typed routing from LIFEOS-1631 as a
  legacy convenience, not the canonical knowledge architecture.
- Document that `raw/` is the evidence/provenance layer and `wiki/` is the
  accumulated durable-knowledge layer; do not require `wiki/sources/` mirrors.

# Out of scope

- Autonomous submit, approval, or application.
- Autonomous deletion, move, rename, split, or merge operations.
- Creating a note for every noun, tag, named entity, or extracted keyword.
- Requiring a domain ontology, fixed folder taxonomy, or fixed note type metadata.
- Semantic merge logic inside deterministic LifeOS code; the external agent still
  supplies reviewed candidate content.

# Acceptance criteria

- MCP guidance follows `search -> read relevant wiki notes -> decide -> propose`
  and explicitly permits no proposal when a source adds no durable knowledge.
- One draft may contain 1..12 distinct wiki-target operations in any mix of
  generated creates and ownership-aware exact-section updates.
- Each operation has a non-empty rationale that appears in proposal review
  metadata/body.
- Every target is unique, source-grounded, under `wiki/`, and validated before
  publication.
- Existing human-owned updates remain base-hash-bound `patch_human_file`
  operations; generated-owned updates remain ownership/hash checked
  `replace_generated_file` operations.
- A generated create may target an emergent path such as
  `wiki/learning/retrieval-practice.md`; approved application can safely create
  the missing nested `wiki/learning/` parent.
- Arbitrary missing parents outside generated `wiki/` creates remain invalid,
  and symlink/non-directory parent chains fail closed.
- Existing single-page ingestion tools remain compatible but are no longer the
  recommended agent workflow.
- Current docs no longer present `wiki/sources/`, `wiki/entities/`,
  `wiki/concepts/`, or `wiki/syntheses/` as required/preferred structure.

# Validation

```bash
pytest --import-mode=importlib -q tests/ingestion tests/facade/test_proposal_tools.py \
  tests/facade/test_read_only.py tests/proposals/test_application.py \
  tests/proposals/test_validation.py tests/context
pytest --import-mode=importlib -q
python -m compileall -q src/lifeos
python scripts/validate_manual_links.py
git diff --check
```

Run MCP schema/lifecycle tests, Ruff, and strict mypy when those optional toolchain
packages are available in the execution environment.

# Relevant decisions and policy

- `docs/vision.md`: LifeOS is not a giant universal ontology and remains strict
  about consequential mutation.
- DD-079, DD-081, DD-083, DD-084.
- DD-085 is superseded for preferred structure by this task's emergent-structure
  decision while its typed API remains compatibility surface.

# Implementation record

- Added `wiki_search`, a read-only MCP/facade discovery path backed by the
  deterministic lexical search engine and scoped to canonical `wiki/` Markdown.
- Added `ingestion_evolve_wiki_proposal`, the preferred external-agent ingestion
  contract. One draft accepts 1..12 distinct agent-selected generated creates
  and/or ownership-aware exact-section updates, with a required rationale for
  every target selection.
- Kept legacy single-create, single-update, fixed two-operation compound, and
  `page_kind + slug` APIs compatible, but removed them from preferred MCP filing
  guidance.
- Generalized approved generated wiki parent creation from four allowlisted role
  folders to bounded emergent nested paths beneath an already-existing `wiki/`
  root. Symlink, traversal, non-directory, excessive-depth, and non-generated
  missing-parent cases remain fail-closed.
- Added cleanup of newly materialized empty wiki parent folders when application
  fails after directory preparation.
- Preserved existing ownership behavior: human notes use base-hash-bound patches;
  generated notes require matching ownership/generator/content hashes and use
  full generated-file replacements.
- Kept per-page provenance pointed at the registered raw source. No
  `wiki/sources/` mirror is required or automatically generated.
- Bumped the external-agent request provenance schema version from `3` to `4`.
- Added DD-086 and updated architecture, safety, setup, workflow, feature, and
  troubleshooting docs around the principle: semantic policy is minimal;
  mutation policy is strict.
- Added focused unit coverage plus an end-to-end non-MCP lifecycle test proving a
  raw source can create two agent-selected nested wiki notes and update one
  existing human-owned hub atomically without creating `wiki/sources/`.

# Validation record

Validation completed successfully in the supplied sandbox:

```text
Focused compounding/search/proposal tests: 142 passed
Repository regression excluding MCP-only modules: 1418 passed
Agent-directed compounding lifecycle integration: passed
Manual link validator: 14 chapters validated
python -m compileall -q src/lifeos: passed
git diff --check: passed
```

The MCP runtime suite is environment-blocked rather than code-failing. A direct
offline `uv run --python <current> --extra mcp ...` attempt resolved the current
interpreter but could not install `anyio==4.14.2`, required by `mcp==1.28.1`,
because network access is disabled and that wheel is absent from the local uv
cache. The modified MCP source and tests compile syntactically.
