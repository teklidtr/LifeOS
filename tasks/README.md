# Task Workflow

Task states are directories:

```text
backlog/
ready/
in-progress/
completed/
```

A task moves between directories without changing its filename.

Every task must contain metadata, goal, scope, out-of-scope boundaries, acceptance criteria, validation commands, and relevant decisions.

Only `ready/` tasks may be selected. Newly discovered work becomes a separate backlog task.
