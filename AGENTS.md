# LifeOS Agent Instructions

## Mission

Build LifeOS as a private, Obsidian-native system for knowledge, study, adaptive planning, personal observation, and agent-assisted reflection.

It must not become an obligation factory, an opaque autonomous agent, or a second source of truth competing with the Markdown vault.

## Read before acting

For every implementation task, read:

1. `docs/vision.md`
2. relevant sections of `docs/architecture.md`
3. relevant entries in `docs/design-decisions.md`
4. the selected task file
5. any policy linked by that task

Do not rely on chat history when the repository contains the decision.

## Sources of authority

1. Explicit user instruction for the current implementation task
2. `AGENTS.md`
3. accepted decisions in `docs/design-decisions.md`
4. architecture and policy documents
5. task acceptance criteria
6. reversible implementation details inferred by the agent

A vault's `system/instructions.yml` is runtime input for agents using that vault; it is not
an instruction source for changing the LifeOS application unless the selected task explicitly
tests or modifies that runtime contract. Filename alone does not grant authority.

## Implementation workflow

1. Select exactly one task from `tasks/ready/`.
2. Move it to `tasks/in-progress/`.
3. Inspect existing code and tests.
4. Implement only the stated scope.
5. Review documentation impact. Update every affected user manual, architecture, design-decision, setup, operations, or other authoritative document in the same PR. If no documentation is affected, record a concrete reason in the task's `# Documentation impact` section.
6. Run all listed validation.
7. Record discovered work as separate backlog tasks.
8. Move the task to `tasks/completed/` only when all criteria pass, including documentation impact.

Do not opportunistically implement neighboring subsystems.

### Complexity budget and scope control

Correctness and security do not justify unbounded implementation growth. Keep the smallest coherent solution that satisfies the task and its invariants.

1. Treat production code size, changed-file count, new abstractions, and new subsystem dependencies as a complexity budget. If review fixes materially expand that budget, stop and reassess the design before adding more code.
2. When multiple findings are variants of the same invariant, do not keep adding call-site guards. Centralize the invariant once, remove duplicate enforcement where practical, and prefer a net-neutral or net-negative production diff during hardening/consolidation.
3. A review finding is not automatically a requirement to expand the current PR. Fix findings that violate acceptance criteria, documented contracts, correctness, privacy, security, or compatibility. Record independently useful hardening or cleanup that is not blocking the task as follow-up work instead of widening the PR.
4. A zero-finding review is not the completion criterion. Completion is based on the task contract, resolved blocking findings, required validation, and required review classes. Do not keep changing correct code merely to make successive reviewers run out of suggestions.
5. If repeated review rounds keep increasing code size or exposing sibling variants of the same issue, pause the review loop and perform a consolidation/scope audit. If the resulting solution is still disproportionately broad, split independently mergeable work into follow-up tasks or PRs.
6. After a consolidation pass has restored a coherent boundary and broad validation is green, use re-review to validate that boundary rather than restart open-ended hardening. New non-blocking edge-case improvements belong in follow-up work unless they expose a core correctness or security defect.

## Architectural boundaries

- Markdown vault files are canonical human-readable state.
- The registry stores deterministic facts such as hashes, provenance, ownership, and task indexes.
- Agents interpret semantic meaning and create proposals.
- Scripts enforce validation, indexing, patch application, and ownership.
- Generated dashboards and indexes are views, not sources of truth.
- Graphify is an optional, replaceable derived backend.
- Consequential edits require proposals and deterministic application.
- Human-authored content must never be silently rewritten.

## Editing rules

- Read the current target before proposing or changing it.
- Preserve stable IDs, citations, note types, and user-owned sections.
- Modify managed content only inside valid managed blocks.
- Never directly change policies, personal patterns, health conclusions, or important wiki claims outside proposal mode.
- Never treat inferred relationships as established facts.
- Open original notes before using graph-discovered relationships as evidence.

## Documentation impact

Every implementation task must contain a `# Documentation impact` section using the format documented in `tasks/README.md`.

Treat documentation as part of the implementation, not follow-up polish:

- User-visible behavior changes require a review of `docs/user-manual/`.
- Architecture or data-contract changes require a review of architecture/data-model documentation.
- New or changed durable design choices require a review of `docs/design-decisions.md`.
- Installation, configuration, CLI, MCP, or operational changes require setup/operations documentation review.
- Internal-only changes may declare `Status: none`, but must explain why no documented behavior or contract changed.

A completed task file is historical evidence; it does not replace updating the documents that describe LifeOS's current behavior.

## Local validation before CI

CI is an independent verification layer and safety net, not the primary mechanism for discovering deterministic implementation regressions. Agents must make a serious local attempt to catch test failures before pushing a change and before using CI or Codex review as feedback.

For every implementation change:

1. Run the directly relevant regression tests locally before pushing.
2. Run the tests for the affected module or subsystem, including sibling entry points when the changed behavior is shared.
3. When a change touches shared infrastructure, a public facade, multiple subsystems, a trust/privacy boundary, persistence or relocation semantics, or another cross-cutting invariant, run the broadest practical local pytest suite before pushing. Default to the full local pytest suite when the change can plausibly cause failures across multiple test shards or otherwise has a wide compatibility surface.
4. Treat lint, formatting, type checking, compilation, collection, smoke checks, test selection, and cached/incremental test tools as useful accelerators, not substitutes for the behavioral pytest coverage required by the risk of the change. A green fast-check pipeline does not prove behavioral compatibility.
5. Push only after locally reproducible deterministic failures have been fixed. CI should confirm the implementation in an independent environment, not be the first place an ordinary deterministic regression is discovered.
6. If CI finds a deterministic regression that appropriate local validation should have caught, fix the regression, add or strengthen regression coverage when useful, and expand the local validation performed for that class of change before continuing the review cycle.
7. If a required check genuinely cannot run locally, record the limitation and reason in the task or PR, run the closest practical local substitute, and leave the unavailable check to CI explicitly rather than silently treating CI as the default test runner.

Clean-room, container, platform-specific, or other checks whose value specifically depends on the CI environment may remain CI checkpoints. This exception does not remove the obligation to run the relevant local behavioral tests first.

### Refactor and consolidation safety

Refactors and consolidation passes are not behavior-free. When the intent is to preserve behavior while centralizing an invariant or deleting duplication:

1. Before pushing, search the repository for every renamed, removed, or shape-changed helper; monkeypatch target; accessed return attribute; and exact error string changed by the diff. Tests or sibling modules that depend on an underscore-prefixed helper still represent repository compatibility evidence.
2. Preserve existing call shapes, return shapes, patch points, and observable error wording by default when the refactor does not require changing them. If a seam must intentionally change, migrate all known callers and tests in the same change and make the reason explicit.
3. Centralize the invariant at one enforcement boundary and remove or route old duplicate implementations through it. Do not add a new abstraction while leaving parallel security, privacy, filesystem, or identity logic alive elsewhere.
4. When local pytest cannot run, repository-wide dependency search for changed seams is mandatory as the closest static substitute. Ruff, mypy, compilation, and collection cannot detect return-shape, monkeypatch-target, or exact-message compatibility regressions.
5. Before full validation, compare the candidate against the previous known-good head and account for every changed line as required behavior, deliberate consolidation, or regression coverage. Remove incidental cleanup, comment churn, error-text drift, and unrelated refactors from a trust-boundary fix.
6. If CI finds a deterministic compatibility regression after a consolidation pass, treat it as a missed pre-push audit. Restore compatibility unless the change was intentional; otherwise migrate every dependent surface together, broaden the seam search, and only then continue the review cycle.

## Code Review Rules

Use these rules to catch LifeOS-specific invariant violations that may not be obvious from the diff alone. Keep mechanical checks in tests and CI.

### Canonical state and mutation

- Flag any change that lets an agent, adapter, integration, or derived subsystem directly mutate human-authored canonical Markdown, bypass proposal and authorization boundaries, or make disposable/derived state authoritative. Safe path: agents propose semantic changes; deterministic LifeOS code validates and applies explicitly authorized mutations; Markdown remains canonical.

### Privacy and retrieval boundaries

- Flag any read, search, listing, indexing, context, graph, export, or traversal flow where protected or excluded vault content can be accessed, disclosed, or influence results before retrieval policy permits it. Safe path: enforce policy from safe metadata before content access and require explicit protected-scope intent where the contract allows protected access.

### Human authority and semantic truth

- Flag automation that silently rewrites human-owned content, turns uncertain inference into durable fact, or treats agent-generated interpretation as established user truth. Safe path: preserve human-owned text and uncertainty; route consequential semantic changes through reviewable proposals backed by source evidence.

## Pull Request Review Workflow

Codex review is a paid, high-signal checkpoint, not an iterative substitute for implementation, repository-wide reasoning, or CI. Use it only after the implementation agent has made the review surface stable and has exhausted cheaper deterministic validation.

Before a pull request is considered ready to merge:

1. Complete the implementation, documentation impact, and relevant local validation. Ordinary PR pushes should receive a green `fast-checks` result.
2. Before requesting Codex review, stabilize the branch:
   - Resolve all known implementation TODOs, known review findings, and failing deterministic checks first.
   - Run the broadest practical non-Codex validation needed to catch compatibility and regression failures before paying for another review. For changes spanning multiple subsystems, public contracts, or trust boundaries, prefer the full pytest suite and clean-room/Docker validation before another Codex review when practical.
   - Treat this as a pre-review checkpoint, not a replacement for the required final `full-validation` checkpoint.
   - Do not request review while material implementation work is still actively changing the branch.
3. Perform a pre-Codex invariant audit for cross-cutting changes. When a change affects an invariant such as privacy policy, runtime exclusion, stable identity, relocation, proposal authorization, canonical mutation, or an externally callable contract, search all relevant call sites and sibling entry points before requesting review. Do not fix only the single path that exposed the issue if the same invariant can apply elsewhere.
4. Once the implementation is stable and the pre-review audit is complete, request one `@codex review` for the current head.
   - After requesting review, avoid material commits until that review finishes unless a newly discovered correctness or security issue requires an immediate fix.
   - If the head materially changes while a review is in progress, treat that review as evidence about the reviewed snapshot, not as authoritative approval of the new head.
5. Treat the first review as a risk-discovery pass. Triage findings yourself before making edits:
   - Fix findings that are actionable, in scope, and relevant to the task's acceptance criteria or repository invariants.
   - Batch related findings into one coherent correction pass. Do not make one commit or request one re-review per comment.
   - When a finding exposes an invariant with possible sibling violations, search the repository and fix all in-scope variants together.
   - Push a consolidated fix set with focused regression tests and rerun appropriate local validation.
6. Request a second normal `@codex review` only when the first review found material issues and the corrective batch changed behavior, security, or the reviewed contract enough that another pass is justified. Do not request another normal review merely because the previous review had suggestions or non-blocking improvements.
7. If the normal review is clean or only non-blocking follow-up ideas remain, treat the normal review class as stable. Do not continue iterative review rounds trying to force a zero-finding result.
8. For a **security-sensitive PR**, request `@codex security review` only after the normal review stabilizes. Security-sensitive means the change touches authorization, authentication, secrets, privacy boundaries, externally controlled paths/data, canonical mutation safety, recovery integrity, transport security, or public/external service exposure. Apply the same triage rule: fix only actionable in-scope security findings, batch fixes, and request one follow-up security review only if material security behavior changed.
9. After the final material commit and required Codex review classes are stable, request the explicit full-validation checkpoint by adding the `full-validation` label to the PR. The full-validation workflow provides the required `full-test` and `docker-setup-e2e` checks; if `full-validation` is already present from an older head, remove and re-add it so the checkpoint runs against the current commit.
10. Treat a validated checkpoint as tied to that exact reviewed head. If any material commit lands after the successful checkpoint, rerun the affected local validation, obtain re-review when the changed behavior or invariant warrants it, and request a fresh full-validation checkpoint for the new head.
11. Require these gates before merge:
   - ordinary `fast-checks` is green for the final PR head;
   - `full-test` is green for the final PR head;
   - `docker-setup-e2e` is green for the final PR head;
   - all actionable normal/security Codex findings are resolved;
   - no unrelated implementation remains in the branch.

Do not merge a PR merely because Codex produced no findings. Do not merge a PR with known deterministic failures, unresolved blocking findings, stale full-validation evidence, or material implementation work that has not been reviewed. Do not burn repeated Codex reviews on implementation churn that local tests, CI, or repository-wide reasoning should catch first.

## Suggested task sequence

1. Put a clear task in `tasks/ready/`.
2. Move it to `tasks/in-progress/`.
3. Implement it in a branch or worktree.
4. Run required local validation.
5. Push the branch and open a pull request.
6. Let ordinary PR `fast-checks` run on the stable branch head.
7. Complete normal Codex review and any justified re-review on the stable head.
8. For security-sensitive changes, complete the security review after normal review stabilizes.
9. Add the `full-validation` label only after the final material commit and review stabilization, then require green `full-test` plus `docker-setup-e2e`.
10. Mark the task complete only after required validation and review obligations are satisfied.

## Task template

```markdown
---
id: LIFEOS-XXXX
title: Short title
status: backlog | ready | in-progress | completed
phase: N
risk: low | medium | high
---

# Goal

...

# Scope

...

# Out of scope

...

# Acceptance criteria

...

# Documentation impact

Status: required

- `docs/user-manual/...`: describe the user-facing change.

# Validation

```bash
uv run pytest -q tests/path/to/affected_area
uv run ruff check src tests
```

# Relevant decisions

- DD-XXX: ...
```
