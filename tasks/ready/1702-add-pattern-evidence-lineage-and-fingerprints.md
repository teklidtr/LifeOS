---
id: LIFEOS-1702
title: Add personal-pattern evidence lineage and fingerprints
status: ready
phase: 17
depends_on:
  - LIFEOS-1701
risk: high
---

# Goal

Make every durable personal interpretation traceable to the exact evidence versions reviewed when the interpretation was created or changed.

# Scope

- Define normalized evidence references with canonical source path, observed content hash, evidence role, and optional observation/event identity.
- Compute deterministic evidence fingerprints.
- Keep supporting, contesting, and contextual evidence distinguishable.
- Detect missing sources, changed hashes, moved stable-ID sources where supported, ambiguous identities, and deleted evidence.
- Produce typed evidence-state diagnostics.
- Preserve historical reviewed hashes rather than silently advancing references.

# Out of scope

- Deciding whether changed evidence disproves a pattern.
- Vault-wide semantic contradiction search.
- LLM calls.
- Automatic canonical mutation.

# Required invariants

- Path, stable identity, and content version remain separate concepts.
- Source changes create review evidence, not automatic semantic conclusions.
- Historical evidence versions remain inspectable.
- Missing sources remain visible in the evidence set.

# Acceptance criteria

- Evidence fingerprints are deterministic and ordering-independent.
- Changed, moved, missing, ambiguous, and unchanged evidence states are distinguishable.
- Supporting and contesting evidence remain separately traceable.
- Pattern history remains tied to the evidence versions actually reviewed.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document evidence-version semantics.
- `docs/data-model.md`: document evidence-reference shape.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-011
- DD-015
- DD-039
- DD-041
- DD-058
- DD-064
- DD-090
