---
id: LIFEOS-1734
title: Establish a repository-wide Ruff formatter baseline and CI gate
status: completed
phase: hardening
depends_on: []
risk: low
---

# Goal

Make the repository-wide `uv run ruff format --check .` validation meaningful by bringing the existing Python tree onto the locked Ruff formatter baseline, then enforce that baseline in CI so task-listed formatter validation no longer depends on ad hoc local execution.

# Problem evidence

During LIFEOS-1730 validation on 2026-09-06, the locked Ruff 0.15.21 command `uv run ruff format --check .` reported 267 pre-existing files that would be reformatted, including scripts, production modules, and tests unrelated to LIFEOS-1730. The normal `fast-checks` and `full-validation` workflows run `ruff check .` but do not run the formatter check, so the repository can remain lint-clean while the task-standard formatting command fails globally.

# Scope

- Apply the locked Ruff formatter mechanically to the existing Python files that are outside the formatter baseline.
- Review the resulting diff to ensure it is formatting-only and does not alter semantics, generated artifacts, or user-owned content.
- Add the repository-wide `uv run ruff format --check .` command to the appropriate ordinary CI validation path after the baseline is clean.
- Keep Ruff version/configuration sourced from the existing locked development environment; do not introduce a second formatter or style configuration.

# Out of scope

- Behavioral refactors, import/API redesigns, lint-rule expansion, or opportunistic cleanup discovered while formatting.
- Reformatting Markdown, TypeScript, generated files, vendored content, or user vaults unless already selected by the repository's current Ruff configuration.
- Changing task-specific formatter requirements to hide the existing baseline mismatch.

# Required invariants

- The formatting pass must be semantics-preserving and mechanically attributable to the locked Ruff formatter.
- Existing tests, public APIs, error strings, and durable data formats must remain unchanged.
- CI must use the same locked Ruff environment as local/task validation rather than a separately pinned formatter version.
- Do not mix unrelated cleanup into the formatter baseline commit(s).

# Acceptance criteria

- [x] `uv run ruff format --check .` passes from a clean checkout without changing files.
- [x] The repository-wide formatter diff is reviewed as formatting-only; no behavioral changes are bundled into the final baseline.
- [x] Ordinary CI contains a formatter check using the repository's locked Ruff environment.
- [x] `uv run ruff check .`, `uv run mypy src`, and the full pytest suite remain green after the formatting pass.
- [x] Documentation impact is resolved and task workflow validation passes.

# Documentation impact

Status: required
Reason: README maintainer CI documentation must list the new repository-wide Ruff formatter gate; no LifeOS user behavior, architecture, data contracts, setup, or operational semantics change.

# Validation

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
python scripts/validate_tasks.py
```

Follow the root `AGENTS.md` PR review and final-validation workflow before completion.

# Completion evidence

- Locked Ruff 0.15.21 produced the repository-wide baseline; the final ordinary PR head `ee289ed9b0e32cfabfca0b5e4b29b2b60f89e79c` passed the repository formatter gate, Ruff lint, mypy, compileall, pytest collection, project contract smoke tests, task workflow validation, documentation-impact validation, and Obsidian plugin lint/typecheck/test/build.
- Normal Codex review of the stable implementation identified one valid formatter-induced test-fixture regression: a joined `\0` escape consumed the following octal digit. The fixture was corrected to use unambiguous `\x00`, the focused regression test and repository Ruff checks passed, and the review thread was resolved. The fix changed test data spelling only and restored the pre-format runtime bytes.
- GitHub full-validation run `34036421201` passed all four full pytest shards, aggregate `full-test`, clean-room setup/MCP validation, home-node service container validation, ARM64 image build, and aggregate `docker-setup-e2e` for head `ee289ed9b0e32cfabfca0b5e4b29b2b60f89e79c`.
- README maintainer-facing CI documentation records the new formatter gate. No user-manual, architecture, data-contract, setup, or durable design-decision update was required because runtime/user behavior did not change.
- Security review was skipped by explicit current-user instruction.
- No independent out-of-scope follow-up work was discovered.

# Relevant design decisions

- Root `AGENTS.md` local-validation and completion rules require listed deterministic validation to be executable and recorded rather than silently skipped.

# Implementation size and sequencing

Medium mechanical hardening task. Keep it independent from LIFEOS-1730 and other behavioral refactors so formatter churn cannot obscure trust-boundary changes.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** The work is mostly mechanical formatting plus careful diff auditing and CI wiring; medium reasoning is sufficient to guard against accidental semantic changes.
