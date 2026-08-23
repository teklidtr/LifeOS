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
5. Run all listed validation.
6. Record discovered work as separate backlog tasks.
7. Move the task to `tasks/completed/` only when all criteria pass.

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

## Completion standard

A task is complete only when acceptance criteria pass, tests pass, unrelated files remain untouched, and newly discovered work is captured separately.
