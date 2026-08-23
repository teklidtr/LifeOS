---
id: LIFEOS-1616
title: Restore repository-wide Ruff and mypy gates
status: backlog
phase: 16
depends_on:
  - LIFEOS-1633A
risk: medium
---

# Goal

Pay down the pre-existing repository-wide Ruff and strict-mypy debt so the temporary
baseline-aware CI policy introduced by LIFEOS-1633A can be simplified to clean,
repository-wide blocking static-analysis gates.

# Current state

LIFEOS-1633A deliberately made repo-wide Ruff and mypy visible but non-blocking while
blocking new violations in changed Python files. This allowed CI adoption without turning
historical debt into an unrelated prerequisite. The long-term state should still be a
clean repository, not permanent `continue-on-error` audits.

# Scope

- Make `uv run ruff check .` pass for the whole repository.
- Make `uv run mypy src` pass under the existing strict configuration.
- Fix typing ambiguities and lint findings without weakening safety-relevant types or
  disabling broad rule families merely to obtain a green run.
- Preserve runtime behavior with focused regression tests wherever a typing correction
  changes control flow, narrowing, serialization, or public contracts.
- After both repository-wide commands are clean, promote the corresponding CI audit steps
  to blocking gates and simplify redundant changed-file-only static-analysis plumbing
  where doing so improves maintainability.
- Keep the full pytest suite and Docker clean-room setup/MCP gate green throughout.

# Out of scope

- Feature work unrelated to findings reported by Ruff or mypy.
- Large aesthetic refactors that are not needed to restore the baseline.
- Relaxing strict mypy or broadly suppressing errors to make CI green.
- Reworking the runtime, proposal, wiki, or MCP architecture.

# Acceptance criteria

- `uv run ruff check .` exits successfully with no repository-wide findings.
- `uv run mypy src` exits successfully with no errors under the existing strict config.
- CI treats repository-wide Ruff and mypy as blocking checks rather than
  `continue-on-error` audits.
- No broad new ignores or disabled rule families are introduced solely to hide existing
  debt.
- `uv run pytest -q` (using the repository's canonical pytest configuration) passes.
- `./scripts/run-setup-integration-docker.sh` passes.

# Validation

```bash
uv run ruff check .
uv run mypy src
uv run pytest -q
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- LIFEOS-1633A established a temporary baseline-aware CI bridge: new static-analysis debt
  is blocked while historical debt remains visible.
- This task closes that bridge by restoring a clean repository-wide baseline; it must not
  make the temporary policy permanent.
