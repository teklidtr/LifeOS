---
id: LIFEOS-1633A
title: Add GitHub Actions CI and Docker clean-room gates
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1633
risk: medium
---

# Goal

Make repository validation automatic before LIFEOS-1634 changes the setup/bootstrap path.
CI must catch ordinary regressions and independently prove that documented setup plus MCP
works in a clean Linux Docker environment.

# Scope

- Add GitHub Actions CI for pull requests targeting `master` and pushes to `master`.
- Install the locked `dev` and `mcp` extras before validation.
- Keep repo-wide Ruff and mypy results visible as quality audits while existing historical
  lint/type debt is tracked separately.
- Block new Ruff violations in changed Python files and new mypy violations in changed
  Python source files.
- Run compile checks, manual-link validation, and the full pytest suite as blocking gates.
- Run `./scripts/run-setup-integration-docker.sh` as a separate blocking clean-room job.
- Exercise the existing fresh-vault setup contract and a real MCP STDIO handshake inside
  the Docker job.
- Use least-privilege repository permissions.

# Out of scope

- Cleaning all pre-existing repository-wide Ruff or mypy findings as part of CI adoption.
- Changing the runtime/context semantics established by LIFEOS-1633.
- Implementing the Cookiecutter bootstrap in LIFEOS-1634.
- Putting an LLM in deterministic CI pass/fail criteria.

# Acceptance criteria

- A real pull request triggers both normal validation and Docker clean-room jobs.
- Both jobs pass on GitHub-hosted Ubuntu runners.
- New or modified Python files cannot add Ruff violations; modified source files cannot
  add mypy violations.
- Historical repo-wide Ruff/mypy findings remain visible in Actions output without
  preventing CI adoption.
- Compile checks, manual-link validation, full pytest, fresh-vault setup, and real MCP
  STDIO validation are blocking.
- A failed job can be diagnosed from GitHub Actions logs without asking the user to run
  Docker locally.
- LIFEOS-1634 stays non-selectable until this task is completed and the CI gate is green.

# Validation

```bash
uv sync --frozen --extra dev --extra mcp
uv run ruff check .
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
PYTHONPATH=src uv run pytest --import-mode=importlib -q
./scripts/run-setup-integration-docker.sh
```

Repository-wide Ruff and mypy currently serve as audit commands; GitHub Actions applies
blocking checks to changed Python/source files while the historical baseline is cleaned
separately.

# Relevant decisions

- GitHub Actions is the canonical clean-room CI environment; local Docker remains useful
  but is no longer required for the user to diagnose ordinary pull-request failures.
- Correctness/integration gates are blocking. Existing lint/type debt is reported but is
  not retroactively made a prerequisite for introducing CI.
- Python 3.11 remains supported, so MCP/Pydantic schema code and clean-room tests must run
  successfully on Python 3.11.
- The project pins MCP to the 1.x SDK (`mcp>=1.28,<2`); STDIO integration assertions must
  use the v1 SDK model surface while validating the same wire-level semantics.
- LIFEOS-1634 depends on this task and remains in `backlog/` until 1633A is green; after
  completion it can move back to `ready/`.
