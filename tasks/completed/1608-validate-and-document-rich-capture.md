---
id: LIFEOS-1608
title: Validate and document rich capture
status: completed
phase: 16
depends_on:
  - LIFEOS-1607
risk: high
---

# Goal

Complete user documentation, protocol and schema documentation, end-to-end validation, change reports, clean-tree checks, and release packaging.

# Scope

- Implement only this task's named capability and focused tests.
- Preserve canonical Markdown, original bytes, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record explicit degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to external canonical artifacts.

# Required invariants

- Markdown and original attachment bytes remain canonical and portable.
- Unknown and missing values never become zero.
- Estimates remain distinct from confirmed facts.
- Derived state can be deleted and rebuilt.
- Protected content is not sent externally without explicit inspectable intent.

# Required tests

- Full Python and plugin regression, rich-capture end-to-end fixtures, schema and protocol validation, lint, type checking, production build, manual links, provider neutrality, privacy, migration, runtime deletion and rebuild, and packaging checks.

# Acceptance criteria

- Focused Python and plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

- `PYTHONPATH=src .venv/bin/python -m pytest --import-mode=importlib -q tests/captures tests/bridge/test_capture_bridge.py tests/e2e/test_rich_capture.py` -> 48 passed.
- Supported Python regressions in non-overlapping bounded groups -> 1,404 passed: 82 capture/bridge/e2e, 1,158 remaining core suites, 94 optional AI/ingestion, 40 MCP, and 30 integration tests.
- The monolithic Python run reached 82% before the sandbox command window; the same suites then passed completely in bounded groups.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ... -p anyio.pytest_plugin tests/integration` -> 30 passed and exited cleanly.
- `.venv/bin/python -m ruff check` for every Python source and test file changed by Direction 7 -> passed.
- `.venv/bin/python -m mypy src/lifeos/captures` -> passed in strict mode for 17 source files.
- Same-tool repository-wide Ruff comparison with Direction 6 HEAD `5747a58`: 150 findings before and 150 after, in 36 files. The earlier Direction 6 report used an older Ruff release and recorded 148; counts across versions are not directly comparable.
- Same-tool repository-wide mypy comparison with Direction 6 HEAD `5747a58`: 51 pre-existing errors in 16 files before and 51 after.
- `python3 scripts/validate_manual_links.py` -> 14 manual Markdown files validated.
- `npm --prefix packages/obsidian-plugin run lint` -> passed.
- `npm --prefix packages/obsidian-plugin run typecheck` -> passed.
- `npm --prefix packages/obsidian-plugin test` -> 45 passed.
- `npm --prefix packages/obsidian-plugin run build` -> passed.
- `scripts/validate-rich-capture.sh` -> focused tests, provider-neutrality, bridge capabilities, schemas, rebuild, Ruff, mypy, plugin checks, manual links, and diff checks passed.
- Original-file preservation, exact duplicate reuse, same-name different-content handling, deterministic PDF page extraction, audio preservation without fabricated transcription, transcript correction, local and unavailable extraction, cancellation and resume, privacy denial and redaction, nutrition uncertainty, planned versus performed exercise, retrieval and conversation provenance, reviews, experiment evidence, proposals, migration no-op, runtime deletion/rebuild, visualizations, mobile state, and accessibility labels are covered by deterministic fixtures.
- Provider-neutral public contracts and absence of tracked `CLAUDE.md` or `.claude/` files were validated.
- Per-task token counters were not exposed by the execution environment; no raw agent session logs were inspected.
- `git diff --check` -> passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- DD-074 through DD-078
- Rich Capture Architecture
