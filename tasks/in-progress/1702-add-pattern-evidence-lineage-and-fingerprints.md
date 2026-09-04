---
id: LIFEOS-1702
title: Add personal-pattern evidence lineage and fingerprints
status: in-progress
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
- `docs/user-manual/03-feature-breakdown.md`: reviewed; no change required because LIFEOS-1702 adds no user-facing command, UI action, or lifecycle behavior.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Validation evidence

- Local repository checkout is unavailable in the current execution environment: GitHub clone attempts fail DNS resolution, so the repository-wide commands above cannot be run locally here.
- The available local substitute passed: the exact evidence module syntax-compiles, its authored lines stay within the repository line-length limit, the fixed fingerprint vector was independently reproduced, and isolated SQLite smoke coverage passed for fingerprint deduplication/role separation, all six evidence states, immutable reviewed hashes, and caller-authorized stable-ID resolution.
- Repository fast checks and required full validation remain pending on the pull request; this task stays `in-progress` until those checks satisfy the completion rules.

# Relevant design decisions

- DD-011
- DD-015
- DD-039
- DD-041
- DD-058
- DD-064
- DD-090
- DD-095
