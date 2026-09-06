---
id: LIFEOS-1724
title: Consolidate equivalent MCP proposal and research output representations
status: in-progress
phase: hardening
depends_on:
  - LIFEOS-1733
risk: high
---

# Goal

Extend the verified MCP output boundary to equivalent proposal/lifecycle and research-capture results, removing duplicate output descriptions and projections without erasing intentional transport semantics.

# Problem evidence

At planning HEAD `2996540ee16f574503b4226baa417bf55fea380c`, `mcp/models.py` repeats result structures owned by `facade/proposal_tools.py`, `facade/consequential_tools.py`, and `facade/research_tools.py`. The concrete mirrors are `CreateWikiProposalMCPResult`, `UpdateWikiSectionProposalMCPResult`, `CompoundWikiProposalMCPResult`, `EvolveWikiProposalMCPResult`, `StudyLearningProposalMCPResult`, `SubmitProposalMCPResult`, `ApproveProposalMCPResult`, `ApplyProposalMCPResult`, and `ResearchCaptureMCPResult`. Their consumers include registered tools in `mcp/server.py`, `mcp/multi_source_tools.py`, and `mcp/research_tools.py`.

The multi-source evolve tool shares an output mirror with a distinct domain result type. Shape similarity alone does not justify merging domain concepts. Revalidate these paths and the output boundary delivered by LIFEOS-1733.

# Scope

- Migrate compatible create/update/compound/evolve/study, submit/approve/apply, multi-source evolve, and research-capture outputs onto the established authoritative-type output boundary.
- Delete redundant named mirrors and handwritten projections where the full contract matches. Keep authoritative domain result types and feature-specific behavior distinct.
- Inventory remaining MCP output DTOs/projections and record the concrete contract each retained representation supplies.
- Recheck current locked SDK behavior with Context7/upstream source where adoption reveals materially different serialization or validation semantics; reuse LIFEOS-1733's boundary rather than designing another mechanism.

# Out of scope

- Input-model consolidation already owned by LIFEOS-1733, facade/domain rewrites, changes to proposal publication/application, or new dependencies.
- Removing research-query aggregation, registry disclosure/optional-field projections, note-identity renaming, context ranking/provenance conversion, or personal-pattern `to_dict()` transport semantics merely because they return dictionaries.
- Weakening literal draft/lifecycle status constraints where an existing authoritative result is broader than the MCP contract, including any research-create-wiki mismatch.

# Required invariants

- Preserve schemas, required/default/omitted fields, status literals, deterministic path/operation ordering, structured/text payloads, annotations, sanitized errors, and invalid-output rejection, including invalid existing nested instances.
- Preserve direct `tool.fn()` compatibility and every known consumer's return shape; migrate private test seams only with a documented reason and equivalent assertions.
- Trusted runtime mode/actor authority, source/target disclosure rules, review digest, human approval, and explicit application boundaries remain unchanged. Local/HTTP tool exposure, including consequential-tool restrictions, remains unchanged.
- No output refactor may turn a broader domain type into a weaker transport validator or silently expose newly added domain fields.

# Acceptance criteria

- [ ] The named compatible result families use the LIFEOS-1733 boundary and their redundant mirrors/projections are removed.
- [ ] Each retained representation has an explicit contract reason, with requiredness, privacy selection, status constraints, or direct-call behavior identified; no new parallel schema catalog is added.
- [ ] The complete MCP suite covers unchanged generated schemas, success payloads, invalid outputs, direct calls, errors, annotations, and transport-specific tool availability.
- [ ] Existing proposal lifecycle, research capture, multi-source, privacy, and integration tests retain their behavioral assertions.
- [ ] Record net production/concept deletion including adapters. If a family needs substantial field-by-field translation to preserve its contract, keep its intentional DTO rather than enlarging the shared mechanism.

# Documentation impact

Status: required
- Updated `docs/mcp-exploration-architecture.md` with proposal/lifecycle/multi-source/research-capture authoritative-output coverage, legacy schema-name preservation, strict source validation, and the rationale for retained transport-specific representations.
- Reviewed `docs/user-manual/15-mcp-exploration.md`; no edit is required because tool names, arguments, result fields, lifecycle semantics, research workflow, privacy behavior, and transport availability are unchanged.
- Reviewed `docs/architecture.md`; no edit is required because ownership remains unchanged: facades own business/result contracts and `lifeos.mcp` owns transport adaptation. No new capability or durable design decision is introduced.

# Implementation evidence

The LIFEOS-1733 authoritative-output boundary is reused rather than replaced. `build_mcp_tool()` and `serialize_authoritative_output()` accept one narrow optional `output_model_name` override so an authoritative facade dataclass can retain a historical MCP schema title when the facade concept has a different class name. The cache is keyed by both authoritative type and requested model name, so the override does not create a parallel field catalog or change nested model derivation.

Compatible single-source create/update/compound/evolve/study proposal results, submit/approve/apply lifecycle results, the distinct multi-source `EvolveWikiBatchProposalResult`, and `ResearchEvidenceCaptureResult` now supply their own field definitions. The MCP adapters perform strict validation of the already-constructed authoritative result before JSON serialization, preserve tuple-to-list wire/direct-call normalization, and provide the same validated schema to FastMCP. The multi-source facade concept remains distinct even though it intentionally publishes the same historical `EvolveWikiProposalMCPResult` schema as single-source evolve.

Eight redundant mirror symbols are removed from `mcp/models.py`: `UpdateWikiSectionProposalMCPResult`, `CompoundWikiProposalMCPResult`, `EvolveWikiProposalMCPResult`, `StudyLearningProposalMCPResult`, `SubmitProposalMCPResult`, `ApproveProposalMCPResult`, `ApplyProposalMCPResult`, and `ResearchCaptureMCPResult`. The historical name `CreateWikiProposalMCPResult` remains as an intentional transport DTO only for research synthesis; the ordinary single-source create tool now derives that same schema name from `CreateWikiProposalResult`.

## Retained MCP output representations

The remaining explicit MCP DTO/projection inventory is intentional:

- `ReadMarkdownMCPResult`: keeps `source_tags` and `source_topics` required on the transport even though the facade dataclass supplies defaults, preserving published requiredness and direct-call shape.
- `VaultSearchHitMCPResult`, `VaultDiagnosticMCPResult`, `VaultSearchMCPResult`, `VaultLinkMCPResult`, and `VaultLinksMCPResult`: preserve the published exploration schema and handwritten diagnostic projection. In particular, MCP diagnostic `severity` remains the historical unrestricted string rather than opportunistically narrowing the transport schema to the domain diagnostic enum in this task.
- `RegistryRenameMCPResult` and `RegistryRefreshMCPResult`: encode external-disclosure filtering plus optional omission of `renamed`; facade rename tuples are deliberately projected to `{from_path,to_path}` objects only when visible renames exist.
- `ResearchContextSourceMCPResult` and `ResearchQueryContextMCPResult`: aggregate two facade reads, project selected source fields, and add the transport literals `persistence="none"` and `decision_authority="external-agent"`; there is no single authoritative facade result with that contract.
- `CreateWikiProposalMCPResult`: retained specifically for `research_create_wiki_proposal` because `ResearchWikiProposalResult.status` is the broader `str`, while the MCP result must continue to validate `Literal["draft"]`. Reusing the broader facade type would weaken the transport validator.
- `VaultContextInstructionMCPResult`, `VaultContextSourceMCPResult`, `VaultContextDiagnosticMCPResult`, and `VaultContextMCPResult`: preserve external-disclosure selection plus transport-specific ranking/retrieval provenance fields and direct dictionary behavior rather than exposing the complete internal Context Pack model.
- `RuntimeActivityRecordMCPResult` and `RuntimeActivityMCPResult`: preserve privacy-filtered disposable activity selection and optional actor disclosure; the transport does not expose the full internal activity representation.
- `NoteIdentityMCPResult` in `mcp/coherence_tools.py`: selects the externally safe identity facts and renames the internal note path to `current_path`; it does not expose the full coherence snapshot or ambiguous/denied identities.
- Personal-pattern dictionary transport remains outside this DTO list and keeps its feature-owned `to_dict()` semantics as required by the task's explicit out-of-scope boundary.

No retained family required a new field-by-field translation layer merely to claim consolidation.

## Deletion accounting

Against task base `bfe7fc77567aa5ccdea9cb36dc463d5081bea6d2`, the current production `src/` diff is **106 additions and 176 deletions, net -70 lines** before final review fixes. The added lines are primarily the legacy-name option and explicit authoritative type/serialization wiring; the deleted lines remove eight mirror declarations and repeated result projections. Conceptually, the proposal/lifecycle/research-capture field catalogs and their handwritten mappings disappear while the existing LIFEOS-1733 boundary remains the sole authoritative-output mechanism.

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

Local execution was attempted twice from this implementation environment, including after the branch reached its current implementation shape. Both `git clone` attempts failed before checkout with `Could not resolve host: github.com`, so local pytest/Ruff/mypy/task validation cannot be truthfully claimed here. The branch therefore requires the repository's GitHub-hosted `fast-checks`, `obsidian-plugin`, focused/full pytest coverage, and final labeled `full-validation` as independent executable evidence. This environment limitation does not relax any completion gate.

Context7 was rechecked for the Pydantic behavior reused from LIFEOS-1733: dynamic `create_model` models support explicit model names, `from_attributes` recursively reads ordinary objects, and JSON-mode serialization normalizes tuple fields to JSON arrays. No materially new FastMCP serialization mechanism is introduced by this adoption pass.

# Relevant design decisions

- DD-003, DD-004, DD-034, DD-079, DD-083, DD-087, DD-090, DD-091, and DD-092: proposal authority/validation, review history, MCP runtime policy, identity, transport, and batch semantics.

# Implementation size and sequencing

Medium. Depends on LIFEOS-1733 for the single output boundary. No dependency on publication or ingestion internals because their public facade contracts are preserved; avoid editing those internals in this task.

# Recommended Model

- **Recommended model/configuration:** `gpt-5.6-terra`, reasoning effort `high`.
- **Reason for the recommendation:** This is a bounded adoption pass after the difficult SDK boundary is established. Terra is sufficient for the mostly mechanical migrations, with high reasoning reserved for lifecycle literals, disclosure, and direct-call compatibility across the result families.
