---
id: LIFEOS-1702
title: Add personal-pattern evidence lineage and fingerprints
status: completed
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

Status: completed

- `docs/personal-model-architecture.md`: documented evidence-version, fingerprint, source-state, and caller-authorized resolution semantics.
- `docs/data-model.md`: documented the normalized evidence tuple and derived evidence-state diagnostic shape.
- `docs/user-manual/03-feature-breakdown.md`: reviewed; no change required because LIFEOS-1702 adds no user-facing command, UI action, or lifecycle behavior.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Validation evidence

- Local repository checkout was unavailable in the execution environment because GitHub clone attempts failed DNS resolution; `ruff` and `mypy` were also unavailable locally. Consequently the repository-wide commands, including `git diff --check`, could not be executed directly in that local environment.
- Closest local substitutes passed: the authored evidence module syntax-compiled, production lines stayed within the repository line-length limit, the fixed SHA-256 fingerprint vector was independently reproduced, and isolated SQLite smoke coverage passed for fingerprint deduplication/role separation, all six evidence states, immutable reviewed hashes, and caller-authorized stable-ID resolution.
- PR #42 `fast-checks` run #791 passed on material head `be62153e0ee2e53efe2fb12f64486124d4132533`, including documentation impact, manual links, repository Ruff, `mypy src`, compile-all, full test collection, and project contract smoke tests.
- PR #42 Full validation run #179 passed on the same material head, including all four full pytest shards, the aggregate `full-test` gate, and `docker-setup-e2e`.
- The final PR unified diff was inspected as the closest practical substitute for the unavailable local `git diff --check`; no unrelated file changes or whitespace anomaly was identified.
- No independent follow-up work was discovered that requires a separate backlog task.
- Per the user's explicit instruction, code/Codex review and security review were skipped.

# Relevant design decisions

- DD-011
- DD-015
- DD-039
- DD-041
- DD-058
- DD-064
- DD-090
- DD-095
