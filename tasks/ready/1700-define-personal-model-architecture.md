---
id: LIFEOS-1700
title: Define evidence-backed Personal Model architecture
status: ready
phase: 17
depends_on: []
risk: high
---

# Goal

Define the canonical, derived, proposal, privacy, review, and UI boundaries for evidence-backed personal patterns before implementing the subsystem.

# Scope

- Define a personal pattern as a reviewable working hypothesis rather than user truth.
- Define `patterns/*.md` as the canonical artifact boundary.
- Define the aggregate Personal Model as derived and rebuildable.
- Reuse the existing durable lifecycle: `seed`, `active`, `needs-review`, `archived`.
- Keep `confidence` separate from lifecycle state.
- Define evidence references, counter-evidence, source versions, fingerprints, freshness, and review triggers.
- Define deterministic versus agent-assisted responsibilities.
- Define privacy and provider-disclosure boundaries.
- Define integration boundaries with reviews, retrieval, conversations, experiments, goals, plans, and Today.
- Explicitly defer direct pattern-driven planner ranking changes.
- Add a sequenced Phase 17 roadmap and durable design decisions.

# Out of scope

- Habits or routines.
- Calendar integration.
- Monthly or quarterly review artifacts.
- Web/PWA client work.
- Personality typing or medical diagnosis.
- Automatically inferred immutable traits.
- Direct planner optimization from personal patterns.
- A canonical generated `profile/personal-model.md` biography.

# Required invariants

- A pattern remains a hypothesis even when `status: active`.
- Human approval controls durable semantic promotion.
- New evidence never silently rewrites an existing interpretation.
- Counter-evidence is preserved.
- Missing evidence is not negative evidence.
- Derived Personal Model state can be deleted and rebuilt.
- Personal patterns do not grant instruction authority.
- No aggregate productivity, personality, wellness, or life score is introduced.

# Acceptance criteria

- `docs/personal-model-architecture.md` defines the subsystem boundary.
- `docs/roadmap.md` contains Phase 17.
- `docs/data-model.md` contains the proposed pattern artifact model.
- Durable choices are recorded in `docs/design-decisions.md`.
- Canonical patterns are clearly distinguished from the derived Personal Model.
- LIFEOS-1701 through LIFEOS-1710 can be implemented without inventing product semantics.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: define the subsystem.
- `docs/architecture.md`: add the Personal Model layer.
- `docs/data-model.md`: define canonical pattern artifacts.
- `docs/design-decisions.md`: record durable decisions.
- `docs/roadmap.md`: add Phase 17.

# Validation commands

- `python3 scripts/validate_manual_links.py`
- `git diff --check`

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-003: Durable proposal mode
- DD-005: Status and confidence remain separate
- DD-015: Knowledge gaps use evidence signals
- DD-016: Adversarial review is selective
- DD-026: Exercise, diet, and hobbies are not merely productivity inputs
- DD-039: Execution history is canonical; feedback is rebuildable
- DD-041: Missing evidence is not negative evidence
- DD-055 through DD-059: canonical review artifacts and review decisions
