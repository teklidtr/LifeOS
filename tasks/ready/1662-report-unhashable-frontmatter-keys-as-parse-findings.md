---
id: LIFEOS-1662
title: Report unhashable frontmatter keys as parse findings
status: ready
phase: hardening
depends_on:
  - LIFEOS-007
  - LIFEOS-1657
risk: medium
---

# Goal

Make malformed composite YAML mapping keys produce the parser's existing structured
error findings instead of escaping as Python exceptions.

# Problem and evidence

In `src/lifeos/markdown/parser.py:172`,
`StrictSafeLoader.construct_yaml_map` constructs each key and immediately evaluates
`if key in mapping` (line 187). Sequence and mapping keys are unhashable, so this
raises `TypeError`. The caller catches only `yaml.YAMLError` (line 214).

For example, parsing this content raises `TypeError: unhashable type: 'list'`:

```yaml
---
? [left, right]
: value
---
Human body
```

Replacing the key with `? {left: right}` similarly raises for `dict`.
A malformed note can therefore abort a caller expecting `ParsedNote.findings`;
`src/lifeos/registry/file_tracking.py:283` is one such shared-parser entry point.

# Scope

- Reject unhashable YAML keys through the loader's normal constructor-error path,
  retaining useful source-line information and `frontmatter-invalid-yaml` reporting.
- Keep failure handling narrowly tied to invalid YAML keys; do not hide unrelated
  programming errors behind a broad exception handler.
- Add direct parser regressions and a representative registry/indexing regression
  proving one malformed note is reported through the normal invalid-note path.

# Out of scope

- YAML library replacement or a new frontmatter schema.
- Coercing arbitrary keys to strings or rejecting currently supported scalar keys
  without an existing contract requiring it.
- Changes to managed-marker grammar, offsets, metadata interpretation, or mutation
  authorization introduced in LIFEOS-1657.

# Acceptance criteria

- Sequence and mapping keys, including nested frontmatter mappings, never escape as
  `TypeError`; parsing returns an error finding and the existing safe body fallback.
- Valid frontmatter, duplicate-key rejection, merge-key rejection, empty mappings,
  and existing scalar-key behavior remain compatible.
- Managed-block offsets/findings and durable field extraction remain correct for
  valid inputs; invalid frontmatter never authorizes a write.
- A registry/scan entry point handles the malformed note without an uncaught
  exception or mutation of that note.
- Tests cover both composite key kinds and source-line diagnostics.

# Documentation impact

Status: none
Reason: This restores the existing finding-based parser failure contract and uses
an existing error category; valid YAML, user workflows, and durable schemas do not
change.

# Validation

```bash
rtk .venv/bin/pytest -q tests/markdown tests/registry tests/proposals
rtk .venv/bin/ruff check src tests
rtk .venv/bin/mypy src/lifeos
rtk .venv/bin/pytest -q
rtk git diff --check
```

# Relevant decisions

- DD-002: deterministic code owns validation.
- DD-011 and DD-012: malformed input must not bypass current-target/preservation checks.
- `AGENTS.md`: shared-parser changes require sibling-entry-point and broad local
  validation; untrusted-input processing is a security-sensitive review surface.
- LIFEOS-007 defines durable metadata parsing; LIFEOS-1657 defines the structural
  managed-block boundary that must remain unchanged.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-luna`, reasoning effort `medium`.
- **Reason for the recommendation:** The failure is directly reproduced and the
  repair belongs in one loader boundary. Focused reasoning and tests are sufficient
  provided existing YAML semantics and parser error shapes are preserved.
