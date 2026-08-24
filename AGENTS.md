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

Treat code review as an invariant check across the complete exposed surface, not only the lines changed in the current diff.

### Privacy, authorization, and policy boundaries

- Enforce privacy, retrieval, authorization, and routing policy in deterministic code. Prompt text, tool descriptions, or agent instructions may explain policy but must never be the only enforcement layer.
- Review composed and legacy entry points for bypasses whenever a policy-aware surface is added or changed. Equivalent read or mutation paths must enforce the same boundary unless an explicit documented contract says otherwise.
- Apply eligibility and privacy filters before reading, opening, decoding, parsing, scoring, ranking, or descending into denied content whenever the decision can be made from safe path metadata. Protected or excluded content must not affect allowed results or leak through errors and diagnostics.
- Fail closed on symlinks, traversal, special files, malformed canonical state, and other unsafe filesystem states. Error messages exposed to agents must remain bounded and must not disclose denied or host-absolute paths.

### Search, traversal, and bounded exploration

- Apply result limits only after policy filtering and eligibility checks. A bounded search must not let denied higher-ranked candidates crowd valid lower-ranked candidates out of the returned window.
- Path-only operations such as listing must remain path-only. Do not read Markdown contents merely to discover file names or folders.
- Bounded enumeration must remain traversable. If a result can be truncated, provide deterministic continuation or another complete discovery mechanism so an MCP-only caller is not stranded at the first page.

### Parsing, links, and identity

- Preserve link semantics explicitly. Relative Markdown links resolve relative to their source note; Obsidian wikilinks may resolve by canonical path or unique basename.
- Never guess when a basename, durable ID, canonical target, or other identity is ambiguous. Ambiguous identity must fail closed or remain unresolved according to the documented contract.
- Distinguish failure of the explicitly requested source from failure of unrelated candidates. A requested unreadable or structurally invalid note must produce a deterministic tool error; malformed neighboring backlink or search candidates may be omitted or diagnosed according to the documented contract.

### Validation and error contracts

- Validate caller-controlled bounds and shapes at the adapter boundary and again in authoritative business logic where appropriate.
- Expected input failures must become stable argument or validation errors, never generic internal errors.
- Preserve established safe error contracts when refactoring lower-level traversal or I/O. Security hardening must not unnecessarily collapse actionable allowed-path errors into opaque failures.

### Regression and review resolution

- For every accepted review finding that represents a reproducible bug or boundary failure, add a regression test when practical.
- Prefer adversarial tests that prove ordering and composition properties, such as policy filtering before decode or cap, rather than only happy-path examples.
- Before resolving a review thread, run the narrow regression plus the relevant broader validation. Do not mark a finding resolved merely because the implementation appears correct by inspection.

## Completion standard

A task is complete only when acceptance criteria pass, tests pass, unrelated files remain untouched, newly discovered work is captured separately, and documentation impact has been resolved in the same PR. A task that changes documented behavior or contracts without updating the affected documentation is not complete.
