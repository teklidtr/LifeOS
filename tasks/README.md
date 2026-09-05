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

Task `id` values are globally unique across backlog, ready, in-progress, and completed history. Never reuse a completed task ID for new work. IDs must resolve to `LIFEOS-*` identifiers after normal YAML scalar quoting/comment syntax is normalized. `python scripts/validate_tasks.py` recursively validates global ID uniqueness and directory/status agreement; PR `fast-checks` run this validation even for task-only or documentation-only changes. Historical dependency metadata remains governed by the task records themselves and is not normalized by this identity validator.

Only `ready/` tasks may be selected for implementation. Backlog tasks must never be implemented directly.

If `tasks/ready/` contains no task files, an agent may promote exactly one task from `tasks/backlog/` to `tasks/ready/` before selecting work. A backlog task is eligible for promotion only when:

- its required task contract is complete enough to implement without inventing scope;
- every task listed in `depends_on` is already in `tasks/completed/`;
- no explicit current-user instruction or repository rule requires it to remain in backlog.

When promoting a task, move the file to `tasks/ready/` and change its frontmatter `status` from `backlog` to `ready`. If multiple backlog tasks are eligible, promote exactly one rather than filling the ready queue speculatively. Explicit current-user priority takes precedence when choosing which eligible task to promote.

Newly discovered work becomes a separate backlog task.

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
