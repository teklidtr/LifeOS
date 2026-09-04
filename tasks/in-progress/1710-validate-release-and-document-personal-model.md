---
id: LIFEOS-1710
title: Validate, recover, migrate, and document the Personal Model
status: in-progress
phase: 17
depends_on:
  - LIFEOS-1701
  - LIFEOS-1702
  - LIFEOS-1703
  - LIFEOS-1704
  - LIFEOS-1705
  - LIFEOS-1706
  - LIFEOS-1707
  - LIFEOS-1708
  - LIFEOS-1709
risk: high
---

# Goal

Ship Phase 17 as a coherent recoverable feature with conservative migration, end-to-end fixtures, and complete user documentation.

# Scope

- Add runtime deletion/rebuild coverage.
- Add proposal interruption/recovery coverage.
- Add representative histories for stable, weakening, contradicting, stale, archived, and sparse-evidence hypotheses.
- Add bounded large-vault performance fixtures.
- Handle existing Markdown under `patterns/` conservatively and do not auto-convert unrecognized user-authored notes.
- Add migration preview only if a recognizable legacy contract exists.
- Add end-to-end Obsidian lifecycle coverage.
- Add local STDIO MCP and authenticated home-node coverage where relevant.
- Complete user manual and roadmap shipped-state documentation.

# Out of scope

- Habits.
- Calendar.
- Monthly or quarterly reviews.
- Direct planner ranking changes.
- Web client work.
- Broad refactors unrelated to Phase 17.

# Required invariants

- Removing disposable Personal Model state cannot remove canonical patterns.
- Migration never invents semantic status or confidence.
- Existing human Markdown is not silently rewritten.
- Recovery preserves proposal and evidence lineage.
- Release fixtures contain no hidden universal score.

# Acceptance criteria

- Phase 17 works end to end from evidence through proposal, canonical hypothesis, review, re-evaluation, context, and Obsidian inspection.
- `.lifeos/` may be removed and rebuilt without losing Personal Model knowledge.
- Existing arbitrary `patterns/` Markdown remains untouched unless explicitly migrated.
- Full repository validation passes.
- User documentation states clearly that personal patterns are working hypotheses, not truths or diagnoses.

# Documentation impact

Status: required

- `docs/roadmap.md`: mark Phase 17 shipped after completion.
- `docs/user-manual/README.md`: add the Personal Model chapter.
- `docs/user-manual/`: add the complete Personal Model workflow chapter.
- `docs/user-manual/03-feature-breakdown.md`: add the final feature summary.
- `docs/user-manual/06-obsidian-desktop.md`: document final workspace behavior.
- `docs/personal-model-architecture.md`: reconcile shipped contracts.
- `README.md`: mention the evidence-backed Personal Model if appropriate.

# Validation commands

- `python3 scripts/validate_manual_links.py`
- `pytest -q`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- All accepted Phase 17 Personal Model decisions
- AGENTS.md completion and review rules
