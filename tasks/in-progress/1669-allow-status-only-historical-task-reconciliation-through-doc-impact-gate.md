---
id: LIFEOS-1669
title: Allow status-only historical task reconciliation through the documentation-impact gate
status: in-progress
phase: hardening
depends_on: []
risk: medium
---

# Goal

Let the documentation-impact gate accept narrowly scoped metadata-only corrections to legacy
completed task files without retroactively rewriting historical task bodies, while preserving
strict documentation-impact enforcement for implementation work and substantive task edits.

# Problem and current behavior

LIFEOS-1667 changes only stale frontmatter `status` values in 32 files already under
`tasks/completed/`. Those historical files predate the mandatory `# Documentation impact`
section. `scripts/check_documentation_impact.py` currently treats every changed
`tasks/completed/*.md` file as a task declaration that must contain the modern section, so PR
fast-checks fail before any other check can run even though LIFEOS-1667 explicitly forbids
retroactive task-template modernization.

The gate therefore conflates a legacy historical-evidence file receiving a metadata-only state
repair with the selected implementation task whose documentation impact must be declared.

# Scope

- Update the documentation-impact validation contract so a legacy completed task lacking a
  `# Documentation impact` section may be changed only under a narrowly defined historical
  metadata-reconciliation exception.
- Constrain the exception to changes that cannot hide implementation or documentation impact;
  at minimum, substantive task-body, acceptance-criteria, dependency, ID, or implementation
  changes must continue to require the normal declaration.
- Preserve the rule that the selected ready/in-progress/completed implementation task must
  contain a valid documentation-impact declaration.
- Add regression tests covering allowed legacy status-only reconciliation and rejected
  substantive edits to legacy completed tasks.
- Confirm LIFEOS-1667's diff shape passes the gate without adding template sections to its 32
  historical task files.

# Out of scope

- Adding `# Documentation impact` sections retroactively to all historical completed tasks.
- Weakening documentation requirements for current implementation tasks.
- Changing task-state workflow semantics or treating directory placement as optional.
- Changing product behavior, architecture, user-manual content, or unrelated CI checks.

# Acceptance criteria

- A PR that changes only the frontmatter `status` of legacy `tasks/completed/*.md` files can
  pass the documentation-impact gate when the selected implementation task has a valid
  declaration.
- A substantive edit to a legacy completed task without a documentation-impact declaration is
  still rejected.
- ID, dependency, acceptance-criteria, task-body, or other non-allowed changes cannot be hidden
  behind the legacy exception.
- Existing implementation-change and documentation-required gate behavior remains covered and
  passing.
- LIFEOS-1667's historical status-reconciliation shape is covered by a regression test.

# Documentation impact

Status: none
Reason: This is an internal CI compatibility correction for legacy task evidence. It does not
change LifeOS product behavior, user workflows, architecture, setup, or documented task-state
semantics.

# Validation

```bash
pytest -q tests/project/test_documentation_impact.py
python scripts/check_documentation_impact.py --base-ref <known-good-base>
git diff --check
```

# Results

- The candidate checker and exact regression file were executed in an isolated Python harness:
  `19 passed`.
- PR #32 fast-checks runs 726 and 727 passed the documentation-impact gate, manual-link
  validation, Ruff, mypy, source compilation, pytest collection, and `tests/project` smoke suite.
- Codex review of head `416cfde36d8d026051e0808bf35cfb10155dc03b` found two valid P2 issues:
  the legacy baseline must be read from the actual merge base, and newline translation must be
  disabled so byte-sensitive status-only checks cannot hide line-ending rewrites. The task is
  reopened until those findings are fixed and revalidated.
- A repository-local checkout remains unavailable in the current execution environment, so the
  literal local `git diff --check` command could not be run. GitHub unified-diff inspection is
  used as the closest static substitute.

# Relevant decisions

- `AGENTS.md`: documentation impact, scope control, local validation, and PR fast-check rules.
- `tasks/README.md`: task-state directories and frontmatter-state agreement.
- `scripts/check_documentation_impact.py`: current documentation-impact gate behavior.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-sol`, reasoning effort `medium`.
- **Reason for the recommendation:** The change is small but the exception must be shaped
  carefully so legacy compatibility does not create a documentation-gate bypass.
