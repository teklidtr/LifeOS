# LIFEOS-1633A — Add GitHub Actions CI and Docker clean-room gates

Status: in-progress

## Goal

Make repository validation automatic before LIFEOS-1634 changes the setup/bootstrap path. CI must catch ordinary regressions and independently prove that documented setup plus MCP works in a clean Linux Docker environment.

## Requirements

- Add GitHub Actions CI for pull requests targeting `master` and pushes to `master`.
- Run the Python test suite with the locked `dev` and `mcp` extras.
- Run Ruff, mypy, manual-link validation, and compile checks.
- Run `./scripts/run-setup-integration-docker.sh` as a separate clean-room job.
- The Docker job must exercise the existing fresh-vault setup contract and real MCP STDIO handshake.
- CI jobs must use least-privilege repository permissions.
- Keep Docker as a release/clean-room gate rather than the only integration runner.

## Acceptance criteria

- A real pull request triggers both normal validation and Docker clean-room jobs.
- Both jobs pass on GitHub-hosted Ubuntu runners.
- A failed job can be diagnosed from GitHub Actions logs without asking the user to run Docker locally.
- LIFEOS-1634 remains queued until this gate is green.
