# Task Workflow

Task states are directories:

```text
backlog/
ready/
in-progress/
completed/
```

A task moves between directories without changing its filename. When a task moves, its frontmatter `status` must be updated to match the destination directory.

Every task must contain metadata, goal, scope, out-of-scope boundaries, acceptance criteria, documentation impact, validation commands, and relevant decisions.

Task `id` values are globally unique across backlog, ready, in-progress, and completed history. Never reuse a completed task ID for new work. IDs must resolve to `LIFEOS-*` identifiers after normal YAML scalar quoting/comment syntax is normalized. `python scripts/validate_tasks.py` recursively validates global ID uniqueness, directory/status agreement, and enforceable dependency references; PR `fast-checks` run this validation even for task-only or documentation-only changes.

Only `ready/` tasks may be selected for implementation. Backlog tasks must never be implemented directly.

If `tasks/ready/` contains no task files, an agent may promote exactly one task from `tasks/backlog/` to `tasks/ready/` before selecting work. A backlog task is eligible for promotion only when:

- its required task contract is complete enough to implement without inventing scope;
- every task listed in `depends_on` is already in `tasks/completed/`;
- no explicit current-user instruction or repository rule requires it to remain in backlog.

When promoting a task, move the file to `tasks/ready/` and change its frontmatter `status` from `backlog` to `ready`. If multiple backlog tasks are eligible, promote exactly one rather than filling the ready queue speculatively. Explicit current-user priority takes precedence when choosing which eligible task to promote.

Newly discovered work becomes a separate backlog task.

## Dependency metadata

Active tasks in `backlog/`, `ready/`, and `in-progress/` must declare `depends_on` as a YAML-style list of repository task IDs. Inline lists such as `depends_on: [LIFEOS-101, LIFEOS-102]`, multiline `- LIFEOS-*` lists, and the empty list `[]` are supported. Every task ID in an enforceable dependency list must resolve to exactly the repository task identity indexed by `scripts/validate_tasks.py`; an unresolved reference fails validation.

Completed task files are historical evidence and may predate the current dependency contract. The validator therefore indexes a completed task's `id` independently from its dependency metadata. Historical records with no `depends_on` field or with an opaque legacy mapping remain valid task identities, but that missing or ambiguous dependency metadata is intentionally non-enforceable rather than guessed. Historical scalar `depends_on: LIFEOS-*` values and YAML-style lists are deterministic, so their references are enforced. A flow-style empty list on the indented line after `depends_on:` is also accepted as an empty YAML list.

This compatibility boundary is deliberate: old task identities such as `LIFEOS-300`, `LIFEOS-500`, and `LIFEOS-116` remain resolvable even though their completed records omit `depends_on`, while modern task work cannot introduce new ambiguous dependency metadata. Do not rewrite completed scope, acceptance criteria, or implementation evidence merely to modernize formatting.

## Documentation impact

Every implementation task must contain a `# Documentation impact` section. Documentation is part of task completion, not optional follow-up work.

Use one of these two forms.

When documentation must change:

```markdown
# Documentation impact

Status: required

- `docs/user-manual/example.md`: explain the user-visible behavior.
- `docs/architecture.md`: record the changed system contract.
```

When no documentation is affected:

```markdown
# Documentation impact

Status: none
Reason: Internal refactor only; no user-visible behavior or documented contract changed.
```

Rules:

- `Status` must be exactly `required` or `none`.
- `Status: none` requires a concrete non-empty `Reason`.
- `Status: required` means at least one documentation file must change in the same PR.
- Documentation files include `docs/**`, `AGENTS.md`, `README.md`, and `tasks/README.md`.
- User-visible changes must review `docs/user-manual/` even when other technical docs also change.
- Architecture, data-contract, durable design-decision, setup, configuration, CLI, MCP, or operational changes must update their relevant authoritative docs when affected.
- A completed task file records history but does not substitute for current documentation.

CI checks this contract for implementation-changing pull requests.

## Capability discoverability impact

Task contracts that add or materially change user-facing LifeOS behavior must explicitly resolve
capability discoverability. Add a `# Capability discoverability impact` section to that task and
state the semantic registry and Explore decision rather than leaving discovery work implicit.

For user-facing work, use this form:

```markdown
# Capability discoverability impact

Status: required

- Registry: add or update `<semantic-capability-id>` with its concrete LifeOS backing.
- Explore: `explore` because users should discover it directly, or `internal` with the concrete
  rationale for why the grouped behavior is infrastructure rather than an independent ability.
```

Rules:

- A new or materially changed user-facing behavior must add or update its Python-owned semantic
  capability definition even when it composes bridge methods that were already covered.
- A new desktop bridge method added to protocol `CAPABILITIES` must be referenced by a semantic
  capability before completion. Infrastructure/lifecycle/migration/recovery methods belong to an
  explicit `internal` capability with a non-empty description that explains the classification.
- Explore-visible capabilities require concrete LifeOS backing; prompt text alone is not a
  capability.
- Explore and other first-party discovery clients consume the semantic registry and must not own
  a second hard-coded feature catalog.
- The deterministic protocol-coverage audit catches orphan bridge methods, but cannot infer every
  new semantic behavior composed entirely from previously covered methods. Task contract review
  and agent/code review remain mandatory for that case.

Tasks that do not add or materially change user-facing behavior do not need this section.
