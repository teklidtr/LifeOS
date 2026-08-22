---
id: LIFEOS-1631
title: Add typed wiki layout routing
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1630
risk: medium
---

# Goal

Restore the lightweight Karpathy-style filing structure expected by LifeOS wiki
users without turning the vault into a universal ontology.

# Scope

- Define four structural wiki page roles: source, entity, concept, and synthesis.
- Map those roles to `wiki/sources/`, `wiki/entities/`, `wiki/concepts/`, and
  `wiki/syntheses/` using a deterministic portable slug contract.
- Let create-only and compound ingestion requests supply a page role and slug so
  LifeOS can derive the canonical create target; retain explicit `target_path`
  compatibility for existing callers.
- Teach MCP instructions to prefer typed routing for newly generated pages while
  preserving explicit paths for legacy or deliberately custom wiki notes.
- Add the inferred structural `type` to newly generated typed wiki frontmatter.
- Allow proposal application to lazily create only the four known wiki role
  parent directories when the approved operation first needs one; continue to
  reject arbitrary missing parents and unsafe/symlink parents.
- Update architecture, decisions, setup, workflow, feature, and troubleshooting
  documentation.
- Record full multi-page compounding ingestion as separate backlog work.

# Out of scope

- A domain ontology beneath entity or concept pages.
- Automatically creating a page for every noun, topic, or tag in a source.
- Multi-page semantic merge/update of many existing wiki pages in one ingest.
- Automatically maintaining `wiki/index.md`, `wiki/overview.md`, or a wiki log.
- Changing human-owned wiki notes merely to fit the new layout.

# Acceptance criteria

- Typed create requests derive the expected role-folder target and reject invalid
  or ambiguous role/slug/path combinations before proposal publication.
- Legacy explicit `wiki/*.md` targets remain valid.
- Newly generated typed pages contain canonical `type: source|entity|concept|synthesis`.
- Applying an approved create under one of the four role folders creates that
  missing role directory safely and writes the page.
- Missing arbitrary parents remain invalid, and symlink/non-directory parent
  chains remain rejected.
- MCP guidance explains that page roles are filing roles, not a universal
  ontology, and prefers typed routing for new generated pages.
- Focused and full regression tests pass, plus task-scoped Ruff, strict mypy,
  manual link validation, and `git diff --check`.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/ingestion tests/facade/test_proposal_tools.py tests/mcp tests/proposals/test_application.py tests/proposals/test_validation.py tests/integration/test_mcp_ingestion_lifecycle.py
uv run pytest --import-mode=importlib -q
uv run ruff check <changed Python files>
uv run mypy <changed source files>
uv run python scripts/validate_manual_links.py
git diff --check
```

# Relevant decisions and policy

- `docs/vision.md`: LifeOS is not a giant universal ontology.
- DD-001 and DD-002: Markdown remains canonical and semantic interpretation stays
  separate from deterministic facts.
- DD-079: agent-assisted ingestion remains MCP-only.
- DD-081: ingestion remains ownership-aware before publication.
- DD-084: ingestion taxonomy remains agent-proposed and proposal-reviewed.
- `docs/safety-and-ownership.md`: generated writes remain explicit and reviewable.
