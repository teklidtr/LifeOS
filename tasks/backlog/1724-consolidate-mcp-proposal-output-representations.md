---
id: LIFEOS-1724
title: Consolidate equivalent MCP proposal and research output representations
status: backlog
phase: hardening
depends_on:
  - LIFEOS-1723
risk: high
---

# Goal

Extend the verified MCP output boundary to equivalent proposal/lifecycle and research-capture results, removing duplicate output descriptions and projections without erasing intentional transport semantics.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `mcp/models.py` repeats result structures owned by `facade/proposal_tools.py`, `facade/consequential_tools.py`, and `facade/research_tools.py`. The concrete mirrors are `CreateWikiProposalMCPResult`, `UpdateWikiSectionProposalMCPResult`, `CompoundWikiProposalMCPResult`, `EvolveWikiProposalMCPResult`, `StudyLearningProposalMCPResult`, `SubmitProposalMCPResult`, `ApproveProposalMCPResult`, `ApplyProposalMCPResult`, and `ResearchCaptureMCPResult`. Their consumers include registered tools in `mcp/server.py`, `mcp/multi_source_tools.py`, and `mcp/research_tools.py`.

The multi-source evolve tool shares an output mirror with a distinct domain result type. Shape similarity alone does not justify merging domain concepts. Revalidate these paths and the output boundary delivered by LIFEOS-1723.

# Scope

- Migrate compatible create/update/compound/evolve/study, submit/approve/apply, multi-source evolve, and research-capture outputs onto the established authoritative-type output boundary.
- Delete redundant named mirrors and handwritten projections where the full contract matches. Keep authoritative domain result types and feature-specific behavior distinct.
- Inventory remaining MCP output DTOs/projections and record the concrete contract each retained representation supplies.
- Recheck current locked SDK behavior with Context7/upstream source where adoption reveals materially different serialization or validation semantics; reuse LIFEOS-1723's boundary rather than designing another mechanism.

# Out of scope

- Input-model consolidation already owned by LIFEOS-1723, facade/domain rewrites, changes to proposal publication/application, or new dependencies.
- Removing research-query aggregation, registry disclosure/optional-field projections, note-identity renaming, context ranking/provenance conversion, or personal-pattern `to_dict()` transport semantics merely because they return dictionaries.
- Weakening literal draft/lifecycle status constraints where an existing authoritative result is broader than the MCP contract, including any research-create-wiki mismatch.

# Required invariants

- Preserve schemas, required/default/omitted fields, status literals, deterministic path/operation ordering, structured/text payloads, annotations, sanitized errors, and invalid-output rejection, including invalid existing nested instances.
- Preserve direct `tool.fn()` compatibility and every known consumer's return shape; migrate private test seams only with a documented reason and equivalent assertions.
- Trusted runtime mode/actor authority, source/target disclosure rules, review digest, human approval, and explicit application boundaries remain unchanged. Local/HTTP tool exposure, including consequential-tool restrictions, remains unchanged.
- No output refactor may turn a broader domain type into a weaker transport validator or silently expose newly added domain fields.

# Acceptance criteria

- [ ] The named compatible result families use the LIFEOS-1723 boundary and their redundant mirrors/projections are removed.
- [ ] Each retained representation has an explicit contract reason, with requiredness, privacy selection, status constraints, or direct-call behavior identified; no new parallel schema catalog is added.
- [ ] The complete MCP suite covers unchanged generated schemas, success payloads, invalid outputs, direct calls, errors, annotations, and transport-specific tool availability.
- [ ] Existing proposal lifecycle, research capture, multi-source, privacy, and integration tests retain their behavioral assertions.
- [ ] Record net production/concept deletion including adapters. If a family needs substantial field-by-field translation to preserve its contract, keep its intentional DTO rather than enlarging the shared mechanism.

# Documentation impact

Status: required
- `docs/mcp-exploration-architecture.md`: update family coverage and the rationale for remaining transport-specific representations.
- Review `docs/user-manual/15-mcp-exploration.md` and `docs/architecture.md` for affected contract references; no new capabilities or altered proposal semantics are intended.

# Validation

```bash
uv run pytest -q tests/mcp tests/facade tests/ingestion tests/proposals tests/integration
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
python scripts/validate_tasks.py
```

Execute real STDIO/lifecycle tests with the optional SDK installed, plus home-node and runtime-authority regressions. Review schema differences explicitly instead of automatically updating expectations. Follow root `AGENTS.md` for normal/security review and final validation checkpoints.

# Relevant design decisions

- DD-003, DD-004, DD-034, DD-079, DD-083, DD-087, DD-090, DD-091, and DD-092: proposal authority/validation, review history, MCP runtime policy, identity, transport, and batch semantics.

# Implementation size and sequencing

Medium. Depends on LIFEOS-1723 for the single output boundary. No dependency on publication or ingestion internals because their public facade contracts are preserved; avoid editing those internals in this task.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** This is a bounded adoption pass after the difficult SDK boundary is established. Terra is sufficient for the mostly mechanical migrations, with high reasoning reserved for lifecycle literals, disclosure, and direct-call compatibility across the result families.
