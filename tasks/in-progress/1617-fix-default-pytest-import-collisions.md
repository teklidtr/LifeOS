---
id: LIFEOS-1617
title: Make the canonical pytest configuration use importlib mode
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1633A
risk: low
---

# Goal

Make the repository's default pytest invocation behave like the already-green CI suite,
without requiring callers to remember `--import-mode=importlib` on every command.

# Current state

The full suite passes in CI with:

```bash
uv run pytest --import-mode=importlib -q
```

but `pyproject.toml` does not currently make importlib mode the repository default. The
same flag is therefore repeated in CI and integration scripts, and a plain local
`uv run pytest -q` can still use pytest's default import behavior.

# Scope

- Configure pytest centrally in `pyproject.toml` so importlib import mode is the canonical
  repository default.
- Verify same-named test modules in different directories continue to collect as distinct
  modules without import-file mismatch collisions.
- Remove duplicated explicit `--import-mode=importlib` flags from CI/scripts where the
  central configuration makes them redundant and doing so improves clarity.
- Keep test discovery deterministic for local development, GitHub Actions, and Docker
  clean-room validation.

# Out of scope

- Reorganizing the test tree solely to avoid duplicate basenames.
- Changing application package import semantics.
- Fixing unrelated Ruff or mypy debt; that belongs to LIFEOS-1616.

# Acceptance criteria

- `uv run pytest -q` collects and passes the full suite without import-file mismatch
  errors.
- CI no longer depends on a command-line-only import-mode override for correctness.
- Docker/setup integration tests use the same canonical pytest configuration.
- Duplicate test basenames remain independently collected.

# Validation

```bash
uv run pytest -q
uv run pytest --collect-only -q
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- LIFEOS-1633A proved importlib mode on the full GitHub-hosted suite; this task promotes
  that proven behavior from repeated command-line flags into repository configuration.
- One canonical pytest configuration is preferable to subtly different local, CI, and
  Docker invocations.
