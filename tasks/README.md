# Task Workflow

Task states are directories:

```text
backlog/
ready/
in-progress/
completed/
```

A task moves between directories without changing its filename.

Every task must contain metadata, goal, scope, out-of-scope boundaries, acceptance criteria, documentation impact, validation commands, and relevant decisions.

Only `ready/` tasks may be selected. Newly discovered work becomes a separate backlog task.

When `tasks/ready/` contains no implementation task, the implementation agent may promote exactly one task from `tasks/backlog/` to `tasks/ready/` before selection, provided its dependencies are completed and repository authority, dependency ordering, and current architecture make it the next appropriate task. The agent must briefly record why that task is next. If multiple backlog tasks are equally eligible and the repository does not establish an ordering, do not choose arbitrarily; obtain an explicit user decision. Promotion only makes a task selectable; normal `ready/` → `in-progress/` workflow still applies.

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
