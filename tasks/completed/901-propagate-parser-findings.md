---
id: LIFEOS-901
title: Propagate Markdown parser findings into domain loaders
status: completed
phase: hardening
depends_on: []
risk: medium
---

# Goal

Ensure every domain loader handles Markdown parser findings explicitly instead
of silently treating malformed notes as ordinary empty or partial input.

# Discovered issue

`parse_markdown_note()` can report findings for unreadable files, invalid YAML,
and invalid durable metadata types. Several consumers use the returned body or
frontmatter while ignoring `parsed.findings`, which can silently skip work,
include malformed notes with empty metadata, or produce incomplete derived
outputs.

Affected areas include:

- context search and context packs
- study review loading
- adaptive planning loading
- personal observation loading
- graph view construction
- purpose-specific exports

# Scope

- Define a typed domain-loader diagnostic model that preserves source path,
  parser code, severity, and sanitized message.
- Establish an explicit policy for each product:
  - abort because correctness or privacy cannot be established;
  - skip the source and report an omission;
  - continue with a non-authoritative warning.
- Thread findings through text and JSON CLI outputs.
- Ensure public exports fail closed when privacy-related metadata cannot be
  parsed.
- Ensure study, planning, and observation never silently reinterpret malformed
  metadata as missing metadata.
- Ensure graph and context outputs identify omitted or degraded sources.
- Deduplicate repeated findings deterministically.

# Out of scope

- Automatically repairing malformed Markdown or YAML.
- Inventing metadata defaults to hide parser failures.
- Changing parser syntax or canonical schema definitions.
- Sending findings to an external telemetry service.

# Required tests

- Invalid YAML in every affected domain.
- Unsupported durable metadata value types.
- Unreadable or concurrently removed source files.
- Public export with malformed privacy metadata fails closed.
- JSON output exposes stable diagnostic codes and source-relative paths.
- Text output is useful without leaking host filesystem paths.
- Multiple findings are deterministically ordered and deduplicated.
- A clean vault produces no additional diagnostics or output changes.

# Acceptance criteria

- No migrated consumer discards `parsed.findings` without an explicit policy.
- Silent omission of malformed source notes is eliminated.
- Privacy-sensitive operations abort when source classification is uncertain.
- All partial results declare their omissions and evidence limitations.
- Diagnostic behavior is covered at both service and CLI boundaries.

# Validation commands

```bash
pytest tests/markdown tests/context tests/study tests/planning tests/observation tests/graph tests/exports tests/cli
pytest
ruff check src tests
mypy src
git diff --check
```

# Relevant design decisions

- DD-001: Markdown remains canonical
- DD-002: Deterministic facts and semantic interpretation are separate
- DD-005: Status and confidence
- DD-012: Preservation checks are scripted
- DD-015: Knowledge gaps use evidence signals
- DD-029: Optional purpose-specific exports
