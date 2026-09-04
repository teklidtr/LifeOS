# Derived Personal Model Read Model

## Purpose

The Personal Model read model is a disposable, deterministic index over canonical personal-pattern Markdown. It exists to make tracked working hypotheses easy to inspect and group without creating another semantic authority.

Canonical meaning remains in `patterns/*.md`. The derived index lives under `.lifeos/personal-model/` and can be deleted at any time.

## Build inputs and authority

`lifeos.patterns.build_personal_model_document()` reads recognized canonical pattern artifacts directly from the vault. It reuses the Phase 17 evidence-state resolver and review assessment contracts rather than reimplementing source identity, fingerprints, review timing, or deterministic observation analysis.

The read model does not promote ordinary Markdown into a pattern. A file under `patterns/` participates only when it declares a supported `pattern_schema`. A malformed declared pattern produces a diagnostic. Duplicate stable pattern IDs also produce diagnostics and all ambiguous copies are excluded from healthy status groups until canonical identity is repaired.

The registry participates only as rebuildable factual state for current evidence resolution. It does not become the authority for pattern identity or semantic content. Reviewed evidence hashes remain immutable historical facts in canonical pattern Markdown.

## Typed aggregate

Schema version 1 groups unique valid patterns into four deterministic tuples:

- `active`
- `seeds`
- `needs_review`
- `archived`

Items are ordered by stable pattern ID and canonical path. Each item exposes lightweight index and inspection fields:

- stable pattern ID;
- canonical pattern path and exact content hash;
- title and concise `description`;
- lifecycle status and confidence;
- canonical review reasons;
- origin and optional origin source reference;
- last-reviewed and review-due timestamps plus factual due state;
- reviewed evidence fingerprint and evidence references;
- factual evidence diagnostics;
- categorical evidence health;
- deterministic observation freshness when the supported recipe yields a current candidate;
- current read-only review recommendation and its explicit trigger reasons.

The index deliberately does not copy the human-owned pattern body or generate an aggregate narrative. Callers that need the full hypothesis or reflection follow the canonical pattern path.

## Evidence health

Evidence health is a small categorical summary over the exact 1702 source-state diagnostics, not a score:

- `none`: no reviewed evidence references are declared;
- `healthy`: every reviewed reference resolves to the exact reviewed version;
- `attention`: reviewed evidence moved or changed;
- `unavailable`: reviewed evidence is missing, deleted, ambiguous, or cannot otherwise be established safely.

The underlying per-reference diagnostics remain present, including reviewed path/hash and authorized current path/hash facts. Health never advances the reviewed evidence reference.

## Freshness and review attention

When a pattern declares a supported 1704 deterministic evaluation recipe, the read model reuses that assessment. If the current cautious Phase 7 analysis yields a candidate, the candidate's `freshness_days` is exposed directly. If deterministic freshness cannot be established, the field is `null`; unknown is not replaced with a guessed age.

Review recommendations and trigger reasons are likewise reused from 1704. They are read-only. A recommendation does not change status, confidence, statement, or evidence and does not create a proposal.

If journal observations required by a deterministic recipe cannot be parsed safely, the problem is surfaced as a diagnostic and affected recipes fall back to factual evidence-state and due-time assessment rather than inventing statistical results. An unsupported recipe produces a pattern-scoped diagnostic and the same factual-only fallback.

## Publication and recovery

`PersonalModelService.rebuild()` publishes `model.json` beneath `.lifeos/personal-model/` using the shared crash-consistent derived-generation publisher. Publication therefore uses staged generation files, integrity inventory, an atomic active-generation pointer, recovery metadata, and stale-generation cleanup already used by other disposable LifeOS products.

The serialized model has no build timestamp, so unchanged canonical inputs and the same factual time-dependent states produce stable bytes. `PersonalModelService.active_path()` verifies generation integrity before exposing the active snapshot.

Deleting `.lifeos/personal-model/` removes no canonical knowledge. A subsequent rebuild rereads canonical patterns, recomputes diagnostics, and republishes the derived view. No `profile/personal-model.md` is created.

## Privacy and downstream use

The read model is not a provider payload. Evidence-state resolution still takes an authorized path predicate, and later context/provider integrations must apply their existing privacy and disclosure policies before using pattern material externally.

The derived index must never be treated as instruction authority, a personality prompt, planner policy, or a substitute for reading the canonical pattern when semantic detail matters.
