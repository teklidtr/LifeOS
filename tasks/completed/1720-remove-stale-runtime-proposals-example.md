---
id: LIFEOS-1720
title: Remove stale runtime proposals example directory
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Remove the empty `.lifeos.example/proposals/` skeleton that still implies proposal storage beneath disposable runtime state after the repository moved canonical proposal history to top-level `proposals/<proposal-id>/`.

# Scope

- Remove `.lifeos.example/proposals/.gitkeep` and the resulting empty directory.
- Verify active code, tests, CI, and documentation do not depend on `.lifeos.example/proposals/`.
- Preserve `.lifeos/proposal-validation/` as disposable derived state and top-level `proposals/` as canonical history.

# Out of scope

- Changing proposal lifecycle, validation, or storage semantics.
- Removing other `.lifeos.example/` runtime-shape directories.
- Reworking the bootstrap contract.

# Acceptance criteria

- `.lifeos.example/proposals/` no longer exists in the repository tree.
- No supported runtime or test path refers to `.lifeos.example/proposals/` as proposal storage.
- Current proposal-path documentation remains accurate.

# Documentation impact

Status: none
Reason: Active documentation already states the correct top-level canonical proposal path and no longer lists `.lifeos/proposals/`; this task removes the leftover empty example directory only.

# Validation commands

- `python scripts/validate_tasks.py`
- `pytest -q tests/project`
- `git diff --check`

# Relevant decisions

- DD-031: proposal history is canonical Git-tracked state under top-level `proposals/<proposal-id>/`.
- DD-034: proposal validation is disposable runtime state under `.lifeos/proposal-validation/`.
- LIFEOS-1650: the runtime example must not imply canonical proposals live beneath `.lifeos/`.

# Completion evidence

- Removed `.lifeos.example/proposals/.gitkeep`; the stale runtime proposal example directory is no longer tracked.
- Repository search found no active code, test, CI, or documentation dependency on `.lifeos.example/proposals/` as proposal storage.
- Existing proposal-path documentation remains aligned with DD-031 and DD-034, so no documentation edit was required.
- On implementation head `a067c00074`, PR CI `fast-checks` passed, including task workflow validation, documentation gate, Ruff, mypy, compile, pytest collection, and `tests/project`; the `obsidian-plugin` job also passed lint, typecheck, tests, and build.
- `git diff --check` passed against a local reconstruction of the exact PR diff after direct checkout was unavailable because this execution environment could not resolve `github.com`.
- Normal `@codex review` reviewed implementation head `a067c00074` and reported no major issues.
- Security review was skipped per user instruction.
