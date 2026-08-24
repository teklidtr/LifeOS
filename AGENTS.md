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

## Code Review Rules

Use these rules to catch LifeOS-specific invariant violations that may not be obvious from the diff alone. Keep mechanical checks in tests and CI.

### Canonical state and mutation

- Flag any change that lets an agent, adapter, integration, or derived subsystem directly mutate human-authored canonical Markdown, bypass proposal and authorization boundaries, or make disposable/derived state authoritative. Safe path: agents propose semantic changes; deterministic LifeOS code validates and applies explicitly authorized mutations; Markdown remains canonical.

### Privacy and retrieval boundaries

- Flag any read, search, listing, indexing, context, graph, export, or traversal flow where protected or excluded vault content can be accessed, disclosed, or influence results before retrieval policy permits it. Safe path: enforce policy from safe metadata before content access and require explicit protected-scope intent where the contract allows protected access.

### Human authority and semantic truth

- Flag automation that silently rewrites human-owned content, turns uncertain inference into durable fact, or treats agent-generated interpretation as established user truth. Safe path: preserve human-owned text and uncertainty; route consequential semantic changes through reviewable proposals backed by source evidence.

## Pull Request Review Workflow

Before a pull request is considered ready to merge:

1. Complete the implementation, documentation impact, and relevant local validation. Ordinary PR pushes should receive a green `fast-checks` result.
2. Once the implementation is stable, request `@codex review`.
3. Address valid findings, add regression coverage where appropriate, and re-run the relevant validation.
   - Review findings are normally implemented by the current implementation agent. Do not comment `@codex address that feedback` or otherwise delegate implementation to Codex merely because Codex found the issue.
   - Use `@codex address that feedback` only as an exceptional fallback when a finding is too complex to resolve safely within the current implementation effort. If used, review Codex's resulting diff as external implementation work, preserve repository invariants, add or update regression coverage, and run the normal validation before resolving the finding.
4. Request another `@codex review` when review fixes materially change behavior, architecture, public interfaces, trust boundaries, or a substantial portion of the implementation. Batch related fixes before requesting the next review. Do not request another review for trivial or purely mechanical changes.
5. Repeat the review/fix cycle only while material changes continue to be introduced.
6. For a security-sensitive pull request, request `@codex security review` after the normal review cycle has stabilized.
7. Address valid security findings and re-run affected validation. Request another security review only if those fixes materially change a security or trust boundary.
8. After the final material commit and required review cycle are stable, request the GitHub full-validation checkpoint by adding the `full-validation` label to the PR. The checkpoint must produce green `full-test` and `docker-setup-e2e` checks for the current PR head. If material commits land afterward, remove and re-add the label to request a fresh checkpoint without a dummy commit.
9. Do not merge while `fast-checks`, the latest required full-validation checkpoint, or relevant review findings are unresolved or failing.

### Security-sensitive changes

Treat a pull request as security-sensitive when it changes or exposes areas such as:

- authentication, authorization, permissions, or protected-scope enforcement
- privacy or retrieval-policy boundaries
- MCP, API, or other externally callable surfaces
- filesystem access, path traversal, or symlink handling
- canonical-state mutation or proposal/authorization boundaries
- secrets, credentials, configuration trust, or external execution boundaries
- parsing or processing of untrusted external input

Security review is not required for changes that clearly do not affect a security boundary, such as documentation-only edits or isolated presentation changes.

## Completion standard

A task is complete only when acceptance criteria pass, tests pass, unrelated files remain untouched, newly discovered work is captured separately, and documentation impact has been resolved in the same PR. A task that changes documented behavior or contracts without updating the affected documentation is not complete.
