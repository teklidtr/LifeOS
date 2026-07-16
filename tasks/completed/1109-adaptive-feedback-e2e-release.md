---
id: LIFEOS-1109
title: Validate and release the adaptive-planning feedback loop
status: completed
phase: 11
depends_on:
  - LIFEOS-1101
  - LIFEOS-1102
  - LIFEOS-1103
  - LIFEOS-1104
  - LIFEOS-1105
  - LIFEOS-1106
  - LIFEOS-1107
  - LIFEOS-1108
risk: high
---

# Goal

Ship adaptive planning as a trustworthy, measurable, reversible feature with
historical replay, cross-component tests, safe migration, and complete user
manual coverage.

# Scope

- Add end-to-end tests covering capture, planning, execution, reconciliation,
  evidence rebuilding, calibration, adaptation, explanation, diagnosis,
  proposal review, and reset.
- Add fixture histories for:
  - sparse data
  - consistent underestimation
  - inconsistent behavior
  - changing routines
  - repeated avoidance
  - corrected and retracted outcomes
  - missing and malformed records
  - long periods of inactivity
- Add historical replay and shadow-mode evaluation tools.
- Compare baseline and adaptive menus using documented measures such as capacity
  overflow, unused time, completion fraction, estimate error, and explanation
  coverage without inventing one universal productivity score.
- Test time decay, concept drift, resets, schema upgrades, and rebuilds.
- Add performance budgets for realistic and large histories.
- Add release checks for Python, bridge, plugin, protocol, and runtime schema
  compatibility.
- Update `docs/architecture.md`, `docs/design-decisions.md`, and
  `docs/roadmap.md` to match shipped behavior.
- Update `docs/user-manual/` with:
  - adaptive feedback architecture and privacy boundaries
  - execution evidence and what is canonical versus derived
  - **Why this?**, baseline comparison, and confidence explanations
  - correcting outcomes and excluding evidence
  - off, shadow, and active modes
  - repeated-avoidance diagnosis and plan proposals
  - reset, troubleshooting, and recovery instructions
  - revised daily and weekly workflows
- Preserve chapter navigation and validate all manual links.

# Out of scope

- Claiming that adaptive planning improves health, happiness, or productivity in
  general.
- Cloud telemetry or A/B testing on real users.
- Autonomous plan rewriting.
- Semantic retrieval and knowledge conversations.
- Mobile parity.

# Required invariants

- Adaptive mode can be disabled without migration or data loss.
- Historical replay never mutates the vault.
- Evaluation distinguishes missing evidence from negative outcomes.
- No aggregate metric becomes a hidden user score.
- Upgrade failure leaves canonical history and plans intact.
- Documentation describes only shipped behavior and clearly labels limitations.
- Removing derived feedback returns the planner to baseline behavior.

# Required tests

- Complete daily loop with adaptive mode off, shadow, and active.
- Historical replay determinism.
- Changing behavior and time-decay response.
- Correction, exclusion, dismissal, disabled dimension, and full reset.
- Schema upgrade and incompatible-version rejection.
- Registry and derived-feedback deletion followed by clean rebuild.
- Plugin and bridge restart during feedback actions.
- Proposal interruption and recovery from a feedback-driven plan revision.
- Accessibility and keyboard-only critical paths.
- User-manual internal links, commands, screenshots or diagrams, and navigation.

# Acceptance criteria

- Adaptive planning is demonstrably bounded, explainable, and reversible.
- A new user can understand and operate it from Obsidian without terminal
  commands after installation.
- The user manual matches the shipped interface and safety model.
- All Python and TypeScript tests, lint, type checks, builds, release checks, and
  Markdown validation pass.

# Validation commands

```bash
pytest -q
ruff check src tests
mypy src
npm --prefix packages/obsidian-plugin ci
npm --prefix packages/obsidian-plugin run lint
npm --prefix packages/obsidian-plugin run typecheck
npm --prefix packages/obsidian-plugin test
npm --prefix packages/obsidian-plugin run build
./scripts/validate-release.sh
python scripts/validate_markdown_links.py docs/user-manual

git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-007: Native Obsidian references first
- DD-021: Adaptive planning, not conventional task management
- DD-025: Energy and motivation are distinct
- DD-027: Skipped tasks trigger diagnosis
- DD-030: Scope-local logs are generated views
- DD-033: SQLite disposability and rebuilding
