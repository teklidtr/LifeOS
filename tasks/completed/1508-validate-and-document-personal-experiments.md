---
id: LIFEOS-1508
title: Validate and document personal experiments
status: completed
phase: 15
depends_on:
  - LIFEOS-1507
risk: high
---

# Goal

Complete user documentation, protocol and schema documentation, end-to-end validation, change reports, clean-tree checks, and release packaging.

# Scope

- Implement only this task's named capability and its focused tests.
- Preserve canonical Markdown, human-owned regions, proposal gating, provider neutrality, and UI-first behavior.
- Record diagnostics and degraded states instead of inventing evidence.

# Out of scope

- Medical diagnosis or autonomous treatment advice.
- Provider-specific canonical fields.
- Silent mutations to goals, plans, habits, tasks, metrics, notes, reminders, or calendars.

# Required invariants

- Markdown remains canonical and portable.
- Missing observations never become zero.
- Derived state can be deleted and rebuilt.
- Unsafe experiments fail closed before scheduling or activation.
- Descriptive evidence never produces a causal claim.

# Required tests

- Full Python/plugin regression, lint, typecheck, build, links, provider-neutrality, rebuild, migration, and packaging validation.

# Acceptance criteria

- Focused Python and/or plugin tests pass.
- Relevant schema, protocol, type, lint, and build checks pass.
- Task documentation and implementation remain synchronized.

# Validation commands

- `PYTHONPATH=src python3 -m pytest -q tests/experiments tests/bridge/test_experiment_bridge.py tests/e2e/test_personal_experiments.py`: 28 passed.
- All Python regression directories, run in bounded importlib groups: 1,242 passed.
- Optional AI tests: passed after installing the declared `ai` extra.
- Optional MCP tests: 40 passed; the four MCP ingestion lifecycle integration tests passed with plugin autoload disabled to ensure a clean subprocess exit.
- `python3 -m ruff check` for every Python file changed by Direction 6, including the end-to-end fixture: passed.
- `python3 -m mypy src/lifeos/experiments`: passed in strict mode for 16 source files.
- Repository-wide Ruff baseline: 148 pre-existing findings remain outside the Direction 6 changed-file gate.
- Repository-wide mypy baseline: 51 pre-existing findings remain in 16 files outside the new experiment package.
- `python3 scripts/validate_manual_links.py`: 13 chapters validated.
- `npm --prefix packages/obsidian-plugin run lint`: passed.
- `npm --prefix packages/obsidian-plugin test`: 39 passed.
- `npm --prefix packages/obsidian-plugin run build`: passed.
- `LIFEOS_SKIP_PLUGIN_CHECKS=1 scripts/validate-personal-experiments.sh`: passed; plugin checks passed separately because the combined command exceeds the sandbox command window.
- Provider-neutral public contracts, bridge capabilities, schema version, runtime deletion/rebuild, stale writes, unsafe blocking, missing values, migration source hashes, and absence of tracked Claude-specific files: validated.
- Per-task token counters were not exposed by the execution environment; no raw agent session logs were inspected.
- `git diff --check`: passed.

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-003: Durable proposal mode
- DD-036: Obsidian is the primary interface and Python is the sole business-rule engine
- Personal Experiment Architecture
