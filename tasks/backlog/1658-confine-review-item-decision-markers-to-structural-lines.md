---
id: LIFEOS-1658
title: Confine review-item decision markers to structural lines
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1302
  - LIFEOS-1657
risk: high
---

# Goal

Prevent marker-looking text in review-item examples or source excerpts from being
treated as visible artifact authorization for a canonical review decision or
proposal reference.

# Scope

- Define a fail-closed structural grammar for `lifeos:item` markers inside the
  parsed `items` managed block.
- Recognize item markers only on unindented whole lines outside valid Markdown
  fenced code blocks.
- Bind each recognized item ID to exactly one fingerprint and reject duplicate,
  conflicting, or otherwise ambiguous marker structure.
- Route review decision authorization through the structural scanner instead of
  unanchored regular-expression matches over arbitrary block text.
- Audit item rendering and fingerprint extraction for compatibility with the
  structural contract.
- Add adversarial regressions for fenced, indented, list-nested, and block-quoted
  marker examples, including proof that a fake marker cannot authorize a
  decision or proposal while a normally rendered marker still works.

# Out of scope

- Changing review item IDs, fingerprint algorithms, or canonical artifact
  layout.
- Changing review decision semantics or proposal approval policy.
- Implementing a complete CommonMark container parser.
- Refactoring unrelated review rendering or frontmatter parsing.

# Acceptance criteria

- Only one structurally valid, unambiguous `lifeos:item` marker can authorize a
  decision for its exact item ID and fingerprint.
- Marker-looking content inside fenced code, indented code, lists, or block
  quotes cannot authorize a canonical decision or proposal reference.
- Duplicate or conflicting item markers fail closed before canonical state is
  changed.
- Existing valid rendered review artifacts and decision workflows remain
  compatible.
- Focused review tests, Ruff, mypy, and the broadest practical pytest suite pass.

# Documentation impact

Status: none

Reason: this restores the existing contract that visible, structurally rendered
review items authorize decisions; it does not change the artifact format or user
workflow.

# Validation

```bash
.venv/bin/pytest -q tests/reviews
.venv/bin/ruff check src tests
.venv/bin/mypy src/lifeos
.venv/bin/pytest -q
git diff --check
```

# Relevant decisions

- DD-001: canonical Markdown remains authoritative.
- DD-002: deterministic code enforces mutation boundaries.
- DD-009: managed-content authorization is restricted to valid explicit
  structure.
- DD-011 and DD-012: scripted writes read current targets and preserve
  human-owned content.
- DD-038: direct canonical writes retain optimistic concurrency and idempotency
  protections.
- LIFEOS-1657: managed-block and fence structure is parsed through one shared
  fail-closed boundary.
