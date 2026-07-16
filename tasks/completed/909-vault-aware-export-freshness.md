---
id: LIFEOS-909
title: Vault-aware export freshness status
status: completed
phase: hardening
depends_on:
  - LIFEOS-903
  - LIFEOS-907
risk: medium
---

# Goal

Make export status distinguish a readable historical bundle from a bundle that
no longer represents the current canonical vault selection.

# Discovered integration failure

A comprehensive cross-component test built a `public-wiki` export, changed the
canonical source note, and then expected export status to become stale:

```python
build_export(vault_root=vault, runtime_dir=runtime, kind="public-wiki")
(vault / "wiki" / "note.md").write_text(updated_source)
assert export_status(
    runtime_dir=runtime,
    kind="public-wiki",
).status == "stale"
```

The test failed because the current result remained `ready`:

```text
E       AssertionError: assert 'ready' == 'stale'
```

`export_status()` currently receives only `runtime_dir` and `kind`. It can
validate persisted publication metadata, but it cannot recompute the canonical
selection or compare the active manifest's `source_hash` with current vault
state. `lifeos status` therefore reports exports as healthy even after relevant
canonical notes change.

# Why this is not an on-the-spot fix

The correct fix changes a public status API and its CLI/status callers, and must
reproduce export selection semantics exactly. A partial hash comparison could
misclassify bundles when visibility, archived status, malformed notes, selected
roots, or rendering policy changes. This requires a deliberate contract rather
than adding one conditional.

# Scope

- Define an export freshness state that distinguishes at least:
  - `missing`
  - `ready`
  - `stale`
  - `failed`
- Make freshness inspection vault-aware, either by:
  - adding `vault_root` to `export_status()`, or
  - introducing a separate typed freshness inspection API used by CLI/status.
- Reuse the exact canonical selection rules used by `build_export()`.
- Recompute the deterministic aggregate source hash without publishing output.
- Treat changes in selected roots, visibility, archived status, parser
  diagnostics, and rendering-policy version as freshness-relevant.
- Update `lifeos export status` and `lifeos status` to report stale exports.
- Preserve read-only behavior. Status inspection must not create directories,
  recover publication state, or rebuild an export.
- Keep host paths and raw exception representations out of user-facing output.

# Out of scope

- Automatic export rebuilding.
- Continuous background synchronization.
- Remote publication or upload checks.
- Comparing rendered bytes for integrity; that is tracked separately by
  LIFEOS-910.

# Required invariants

- A bundle is `ready` only when its manifest represents the current canonical
  source selection and current rendering policy.
- A source edit, inclusion/exclusion change, or visibility change makes the
  corresponding export stale.
- Changes outside an export kind's selected roots do not make it stale.
- Freshness checks are deterministic and read-only.
- Malformed current sources produce a typed failed or blocked diagnostic rather
  than a false `ready` result.

# Required tests

- Editing an included public-wiki note changes status from `ready` to `stale`.
- Adding or deleting an included note makes the export stale.
- Changing `visibility` to or from `private` makes public-wiki stale.
- Changing only an unrelated journal note does not stale public-wiki.
- Archived-note inclusion changes are detected.
- Malformed selected source produces a typed diagnostic.
- CLI text and JSON status agree.
- Top-level `lifeos status` reports `exports-stale` and remains read-only.
- Rebuilding the export returns status to `ready`.

# Acceptance criteria

- Export status can prove whether the active bundle represents current
  canonical input.
- `lifeos status` no longer reports a stale export as healthy.
- The freshness implementation shares selection/hash logic with export
  building instead of duplicating subtly different rules.
- Full tests, Ruff, mypy, and diff checks pass.

# Validation commands

```bash
pytest tests/exports tests/integration tests/status tests/cli/test_export_cli.py
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-017: Original sources remain immutable
- DD-029: Optional purpose-specific exports
- DD-033: SQLite disposability and rebuilding
