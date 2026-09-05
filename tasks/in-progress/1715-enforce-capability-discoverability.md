---
id: LIFEOS-1715
title: Enforce capability discoverability in agent rules and CI
status: in-progress
phase: 17
depends_on:
  - LIFEOS-1712
  - LIFEOS-1713
risk: medium
---

# Goal

Make capability discoverability part of LifeOS's definition of done so new or materially changed user-facing behavior cannot quietly land without being evaluated for the semantic capability registry and Explore.

# Scope

- Update root `AGENTS.md` with an explicit user-facing discoverability rule:
  - every new or materially changed user-facing capability must add or update its semantic capability definition;
  - the implementation agent must evaluate whether the capability belongs in Explore;
  - intentionally non-user-facing/infrastructure behavior must be explicitly classified as internal rather than being omitted accidentally;
  - Explore must consume the registry and must not grow a separately hard-coded feature list;
  - a user-facing feature is incomplete until its discoverability impact has been resolved.
- Update `tasks/README.md` so implementation task contracts must explicitly account for capability discoverability when user-facing behavior is added or materially changed.
- Add deterministic capability-coverage validation using the registry introduced by LIFEOS-1712 and baseline classification from LIFEOS-1713.
- The mechanical coverage check must ensure every low-level desktop bridge method advertised by the protocol `CAPABILITIES` set is either:
  - referenced as backing behavior by at least one semantic capability; or
  - explicitly classified as internal/infrastructure with a non-empty rationale.
- Make the coverage check fail on newly orphaned bridge methods rather than silently allowing them to bypass discoverability review.
- Validate that Explore-visible capability definitions have concrete backing references and are not prompt-only declarations.
- Integrate the capability-coverage check into the repository's existing CI/project-validation path at the narrowest suitable checkpoint.
- Add regression tests with representative cases for:
  - a newly added orphan bridge method failing validation;
  - a method covered by a semantic capability passing;
  - an explicitly internal method with rationale passing;
  - an Explore-visible prompt-only capability failing validation.
- Document the limit of mechanical enforcement: a new semantic user-facing behavior composed entirely from already-covered methods may not be detectable from protocol coverage alone, so `AGENTS.md`, task contracts, and review remain required complementary guardrails.

# Out of scope

- Building or changing the Explore UI; that is LIFEOS-1714.
- Requiring every bridge method to appear as an Explore card.
- Treating infrastructure, migration, recovery, cancellation, or other internal protocol methods as user-facing solely to satisfy coverage.
- Inferring semantic capabilities automatically from function names or prompts.
- Adding a generic feature telemetry/analytics system.
- Blocking changes based on subjective capability categories that cannot be checked deterministically.

# Required invariants

- Human/agent process rules and deterministic CI checks complement each other; CI must not pretend it can infer every semantic product change.
- Internal classification is explicit and reviewable, not a silent escape hatch.
- The coverage audit follows the existing low-level protocol `CAPABILITIES` source instead of maintaining a second independent list of bridge methods.
- Explore-visible capabilities require concrete LifeOS backing behavior; generic prompt text alone never satisfies coverage.
- The enforcement mechanism does not make generated indexes, UI catalogs, or protocol metadata a source of canonical user state.
- Existing privacy, proposal, authorization, and canonical-state boundaries are not weakened to make coverage easier to satisfy.

# Acceptance criteria

- Root `AGENTS.md` states that capability discoverability is part of completion for new/materially changed user-facing behavior and requires registry/Explore evaluation or explicit internal classification.
- `tasks/README.md` makes discoverability impact an explicit task-contract concern for user-facing implementation work.
- A deterministic audit compares the desktop bridge protocol method set with semantic capability backing references/internal classifications.
- Adding an otherwise-valid bridge method without semantic capability coverage or explicit internal rationale causes the audit to fail.
- Existing intentionally internal methods can be classified without forcing them into Explore.
- An Explore-visible semantic capability with no concrete LifeOS backing reference fails validation.
- The audit runs in CI/project validation and has focused regression tests.
- Documentation clearly states that the audit cannot detect every semantic feature built from previously existing methods and that agent/task review remains mandatory for that class of change.

# Documentation impact

Status: required

- `AGENTS.md`: add the capability-discoverability definition-of-done rule for implementation agents.
- `tasks/README.md`: require user-facing tasks to account for capability registry/Explore impact.
- `docs/architecture.md`: document the coverage relationship between low-level bridge methods, semantic capabilities, internal classifications, and Explore.
- `docs/design-decisions.md`: record the durable enforcement model and the intentional split between semantic review and mechanically checkable protocol coverage.

User-manual review: `docs/user-manual/03-feature-breakdown.md` and
`docs/user-manual/06-obsidian-desktop.md` were reviewed. No user-manual edit is required because
this task does not change Explore's visible catalog, interaction model, or runtime behavior; it
adds development/project-validation enforcement for the already documented registry contract.

# Implementation record

- Added a deterministic protocol-to-semantic coverage audit that consumes the existing desktop
  `CAPABILITIES` set and the Python-owned semantic registry rather than introducing another method
  inventory.
- Added project-validation regressions for orphan, covered, internal-with-rationale, and
  Explore-visible prompt-only cases; the existing `tests/project` CI checkpoint therefore owns
  the future-change gate.
- Updated development rules, task-contract rules, architecture, and DD-102 to keep semantic review
  complementary to mechanically checkable protocol coverage.
- Repository-wide seam review found the existing runtime `validate_bridge_methods` call in the
  capability bridge adapter and the baseline registry test; runtime startup behavior remains
  unchanged and the stale baseline-test comment now points at the project gate.
- No independent follow-up work was discovered during implementation.
- Local checkout and the listed local validation commands could not run because this execution
  environment cannot resolve `github.com`. Repository-wide connector searches, exact branch diff
  review, and changed-file inspection are being used as the closest static substitute; GitHub CI
  remains the independent executable validation environment.

# Validation commands

- `pytest -q tests/project`
- `pytest -q`
- `ruff check .`
- `mypy src/lifeos`
- `git diff --check`

# Relevant design decisions

- DD-037
- DD-080
- DD-101
- DD-102
