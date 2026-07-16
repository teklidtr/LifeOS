---
id: LIFEOS-903
title: Export manifest v2 and portable link resolution
status: completed
phase: hardening
depends_on:
  - LIFEOS-901
risk: medium
---

# Goal

Make export manifests accurately distinguish canonical source identity from
rendered output identity, and make exported Markdown links portable from every
nested output path.

# Discovered issue

The current manifest records a `content_hash` after wikilinks have been
rendered. It therefore does not clearly represent the canonical source bytes
promised by the export contract. The manifest also lacks a separate rendered
output hash. Portable link conversion does not use a complete ambiguity-aware
index and can emit paths that resolve incorrectly when the referring note is
nested, when basenames collide, or when headings require Markdown-compatible
anchors and URI encoding.

# Scope

- Define export manifest schema version 2.
- Record both canonical source hash and rendered output hash for every exported
  file.
- Record source-relative path, output-relative path, export purpose, and
  rendering policy version.
- Build one deterministic link-resolution index before rendering files.
- Resolve exact vault-relative links before considering basename aliases.
- Treat ambiguous basename links as explicit diagnostics rather than choosing
  one source by scan order.
- Generate links relative to the referring exported file.
- Preserve headings and blocks when supported, with deterministic anchor and
  URI encoding rules.
- Report unresolved, ambiguous, excluded-private, and out-of-bundle targets.
- Support reading version 1 manifests long enough to rebuild them as version 2,
  or document and test an explicit rejection path.

# Out of scope

- Rewriting canonical wikilinks in the vault.
- Guaranteeing compatibility with every Markdown renderer.
- Publishing bundles to a remote host.
- Resolving links to files intentionally excluded from the selected export.

# Required tests

- Source hash remains the hash of canonical source bytes after link rendering.
- Rendered output hash changes when rendering changes.
- Nested source linking to a sibling, parent, and deeply nested target.
- Duplicate basenames in different directories.
- Exact path disambiguates duplicate basenames.
- Heading fragments with spaces, punctuation, Unicode, and URI-sensitive
  characters.
- Link to a private note in public export produces a safe diagnostic and no
  accidental path disclosure.
- Manifest serialization is deterministic.
- Version 1 compatibility or rejection behavior is tested.

# Acceptance criteria

- Every manifest entry clearly identifies both source and rendered content.
- Exported links resolve correctly relative to the referring output file.
- Ambiguous links are never resolved by incidental traversal order.
- Public exports do not expose private target paths through link diagnostics.
- Repeated identical builds produce byte-identical manifests and Markdown.

# Validation commands

```bash
pytest tests/exports tests/cli/test_export_cli.py
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-007: Native Obsidian references first
- DD-017: Original sources remain immutable
- DD-029: Optional purpose-specific exports
- DD-030: Scope-local logs are generated views
