---
id: LIFEOS-1645
title: Add folder-scoped multi-source ingestion with target-centric reconciliation
status: completed
phase: 16
depends_on:
  - LIFEOS-1628
  - LIFEOS-1632
  - LIFEOS-1638
  - LIFEOS-1639
  - LIFEOS-1643
risk: high
---

# Goal

Add a folder-scoped ingestion workflow in which an external agent can reason over several
registered canonical Markdown sources together and produce **one reviewable atomic knowledge
proposal**, even when multiple sources contribute to the same wiki target.

The current preferred ingestion contract is source-centric: one registered source may produce
1..12 distinct wiki-target mutations. That works well for `one source -> many targets`, but it
creates stale proposal conflicts for `many sources -> overlapping targets`. If three sources are
independently ingested against the same existing wiki note, all three drafts can bind the same
original `base_hash`; after the first proposal is applied, the others correctly fail as stale.
Even non-overlapping section edits to the same file conflict because concurrency is intentionally
file/hash based.

Folder ingestion must therefore **not** be implemented as `for file in folder: ingest(file)`.
The logical ingestion batch should be the proposal boundary: sources are considered together,
semantic contributions are reconciled by the external agent, desired changes are grouped by
`target_path`, and LifeOS publishes at most one patch operation for each target.

# Design principles

- **Batch by evidence, reconcile by target.** Several sources may ground one target mutation,
  but one proposal contains only one authoritative operation for a given target path.
- **Observed evidence versions are explicit.** The batch proposal call carries the exact
  `(path, content_hash)` snapshots the agent actually read. Registry refresh may discover newer
  state but must never silently rebind an old synthesis to different source bytes.
- **Semantic merging stays with the external agent.** Deterministic LifeOS does not decide how
  conflicting claims should be synthesized, which source is more important, or what the final
  prose should say.
- **Mutation policy stays strict.** Human-owned targets remain base-hash-bound patches;
  generated-owned targets remain ownership/hash-bound replacements; approved application still
  fails closed if reviewed state changed.
- **Folder location is scope/context, not authority.** Every source is independently subject to
  vault containment, retrieval/privacy policy, registration, hash verification, and runtime
  exclusion rules.
- **Provenance is target-specific.** A batch-level source union must not falsely imply that every
  source contributed to every changed page.
- **Reviewability is bounded across multiple dimensions.** Source count, distinct target count,
  and total serialized patch/review payload are separate limits; no one dimension substitutes for
  the others.
- **One logical folder batch must not silently fan out into conflicting proposals.** If a folder
  exceeds a documented safety/workload bound, require narrowing or an explicit subsequent batch
  rather than automatically emitting per-source drafts.
- Reuse the existing MCP exploration primitives (`vault_list`, `vault_read_many`, `vault_search`,
  `vault_context`, `wiki_search`) and proposal engine. Do not add an embedded model runtime or a
  second ingestion engine.

# Scope

- Define the folder-ingestion orchestration contract for an external MCP agent:
  1. receive/select a vault-relative folder;
  2. discover eligible canonical Markdown sources beneath that folder using existing bounded
     exploration primitives;
  3. read the selected evidence with `vault_read_many`, retain each exact path/content-hash
     snapshot, and reason over those observed versions jointly with applicable vault context;
  4. search/read relevant existing wiki knowledge;
  5. decide whether the batch warrants zero durable changes or a bounded set of target-centric
     mutations;
  6. publish one draft proposal for the whole logical batch.
- Add a multi-source proposal-producing facade/MCP contract rather than looping over the existing
  single-source mutation tool. The exact public name may follow repository naming conventions,
  but the contract must accept a bounded ordered set of observed source snapshots
  (`path` + `content_hash`) plus target-centric agent mutations.
- Keep the initial source batch bounded. Use a deterministic documented maximum of **64 source
  paths per proposal** unless implementation evidence recorded in this task justifies a smaller
  bound. Exceeding the bound must fail or require explicit narrowing; it must not silently split
  the batch into multiple conflicting proposals.
- Define a folder/multi-source-specific target-operation budget rather than inheriting the
  single-source 12-operation limit. Use a deterministic initial maximum of **32 distinct target
  operations per proposal**. The existing single-source contract may retain its 1..12 bound for
  compatibility.
- Add a deterministic total serialized patch/review payload budget in addition to source and
  target counts. Start with **2 MiB per proposal** for the canonical patch/review payload unless
  implementation evidence recorded in this task justifies a smaller limit or an existing stricter
  proposal-engine bound must remain authoritative. Exceeding the byte budget must fail before
  draft persistence and must not silently split the batch.
- Replace the current implicit `one proposal -> one SourceSnapshot` assumption with a model that
  can verify several source snapshots for one proposal while retaining backwards compatibility
  for existing single-source APIs.
- Verify every supplied observation hash against the current registered source after the
  authoritative registry refresh and again immediately before proposal publication. A source that
  changed after the agent read it must fail closed and require reread/reasoning; refresh must not
  silently advance the evidence version. Any missing, unregistered, modified, policy-denied,
  duplicate/ambiguous identity, unsafe, or unreadable source also blocks the whole draft before
  proposal persistence.
- Preserve the existing MCP internal-source boundary: `proposals/`, `conversations/`, and
  configured runtime state cannot become batch ingestion evidence merely because they are
  addressable paths.
- Represent grounding at mutation granularity. Each target mutation must name the subset of
  verified source snapshots that actually support that target. Proposal-level
  `related_sources` may contain the deterministic union, but generated-page provenance and
  review metadata must not indiscriminately attach the full batch to every target.
- Aggregate overlapping desired edits **before** patch construction:
  - a target path appears at most once in `patches.json`;
  - several agent-selected section changes to one human-owned wiki file become one
    `patch_human_file` operation against the single reviewed base hash;
  - several contributions to one generated-owned wiki file become one final
    `replace_generated_file` operation against the single reviewed ownership/content state;
  - a new generated target is created once even when several sources jointly ground it.
- Preserve the current target stable-identity/path/hash contract from LIFEOS-1643 for existing
  notes. Multi-source batching must not weaken relocation, stale-content, ownership, or
  authorization checks. A target that becomes stale while immutable review material is being
  built must surface as an actionable conflict and fail before draft persistence.
- Extend cumulative generated provenance so one reviewed target mutation may merge several
  verified `(path, content_hash)` source snapshots in one operation. Preserve deterministic
  deduplication/history semantics from LIFEOS-1628.
- Make the target-to-source grounding map visible and review-digest-bound. The user must be able
  to inspect which sources support each target mutation without storing hidden chain-of-thought.
  When generated tags change, preserve the supplied tag rationale in digest-bound review metadata
  and human-readable proposal review material.
- Keep proposal application atomic across all target operations. If any target is stale or
  invalid at application time, existing preflight/recovery semantics must prevent partial
  canonical publication.
- Preserve existing single-source ingestion tools as compatibility APIs. Prefer routing their
  implementation through the shared multi-source/target-centric primitive where doing so reduces
  duplicate security, provenance, and mutation logic without changing observable behavior.
- Update MCP instructions so a folder request is described as joint source exploration and one
  target-reconciled draft, not independent ingestion of every file, and requires carrying the
  exact observed source hashes into the proposal call.
- Add deterministic regression coverage for overlapping-source/target cases, including:
  - three sources contributing to three different sections of one human-owned wiki note and
    producing exactly one target operation;
  - three sources contributing to one generated-owned wiki note with all and only the relevant
    source snapshots accumulated in provenance;
  - several sources contributing to several targets with distinct per-target source subsets;
  - a batch using more than 12 but no more than 32 targets and remaining valid when byte/source
    limits are satisfied;
  - one selected source changing after the agent read it and before the batch call, even when
    registry refresh observes the new version, causing the whole proposal to fail closed;
  - one selected source changing during proposal construction and causing the whole proposal
    publication to fail closed;
  - a target changing before immutable review-snapshot construction and surfacing as a conflict;
  - a target changing after draft publication and remaining stale at application time;
  - generated tag rationale remaining visible in digest-bound review artifacts;
  - MCP batch ingestion refusing internal proposal/conversation sources;
  - a folder/batch above the source bound refusing automatic fan-out;
  - a batch above the 32-target bound refusing automatic fan-out;
  - a batch above the total patch/review byte budget failing before draft persistence;
  - existing single-source ingestion behavior remaining compatible.

# Out of scope

- Embedding an LLM, agent loop, provider credentials, or semantic merge algorithm inside LifeOS.
- Automatically deciding which source wins when sources disagree. The external agent supplies the
  reviewed reconciled candidate and rationale.
- Automatically ingesting every file in the vault or watching folders for semantic ingestion.
- Autonomous submit, approval, acceptance, or application after draft creation.
- Weakening file-level optimistic concurrency so independently created stale proposals can merge
  themselves at apply time.
- Generic arbitrary write/delete/move/rename operations.
- Multi-source flashcard generation or study-session batching in this task. Existing study
  ingestion remains source-scoped; batch study pedagogy can be separate follow-up work if needed.
- Changing retrieval/vector indexing or Graphify merely because they consume the resulting wiki
  state.
- Automatically splitting oversized folder batches into several proposals, because that would
  reintroduce the cross-proposal target-conflict problem this task is intended to solve.

# Acceptance criteria

- An MCP-only external agent can take a folder containing multiple eligible Markdown sources,
  inspect them with existing exploration/context/search tools, retain their observed content
  hashes, and create **one** draft knowledge proposal grounded in those exact verified source
  snapshots.
- Folder ingestion does not call the single-source proposal workflow once per file and does not
  emit multiple drafts merely because the folder contains multiple sources.
- The multi-source proposal contract accepts at most 64 distinct source paths/snapshots and
  refuses an oversized logical batch without silently fan-out/splitting it.
- A source changed after the agent read it cannot be silently rebound by registry refresh: the
  supplied exploration-time hash must still match the registered/current source before proposal
  construction and immediately before persistence, otherwise the whole batch fails closed.
- The multi-source proposal contract accepts at most **32 distinct target operations**, independent
  of the legacy single-source 12-target limit, and refuses an oversized target set without silent
  fan-out/splitting.
- The serialized canonical patch/review payload is bounded to **2 MiB per folder-ingestion
  proposal** unless implementation evidence in this task records a stricter authoritative limit;
  oversized payloads fail before draft persistence rather than being silently split.
- The final patch document contains at most one operation for each `target_path`, even when
  several sources or several desired section changes affect that target.
- Three independent contributions to one human-owned file are reconciled into one unified
  base-hash-bound `patch_human_file` operation, so applying the batch does not create sibling
  proposals that immediately stale each other.
- Multi-source generated-file creation/replacement records target-specific cumulative provenance:
  every relevant source snapshot is preserved, unrelated batch sources are absent, exact
  `(path, content_hash)` duplicates are deduplicated, and prior accepted history remains intact.
- Proposal review artifacts expose a deterministic target-to-source grounding map plus mutation
  rationale and bind it to the ordinary review digest without exposing hidden reasoning. Reviewed
  generated-tag changes also preserve their tag rationale in those review artifacts.
- Every source in the request is independently containment/policy/registration/hash validated
  before draft persistence; one invalid or changed source aborts the whole proposal publication.
  `proposals/`, `conversations/`, and configured runtime state remain unavailable as MCP batch
  ingestion evidence.
- Existing target ownership, stable identity, path, reviewed base hash, stale-write, immutable
  review snapshot, authorization, application, rollback, and recovery invariants remain intact.
  A concurrent target edit during review-snapshot construction is reported as a conflict rather
  than an opaque internal error.
- Application remains atomic: one stale/invalid target prevents partial application of the rest
  of the folder batch.
- Existing `ingestion_evolve_wiki_proposal` and other compatibility single-source APIs continue
  to pass their current tests and preserve their public behavior.
- MCP guidance explicitly describes folder ingestion as `discover -> vault_read_many + observed
  hashes -> inspect context/wiki -> jointly reason -> group by target -> one draft`, states that a
  changed observed source requires reread/reasoning, and states that zero durable changes remains
  a valid result.
- No semantic provider runtime, universal ontology, database authority, or hidden automatic merge
  policy is introduced.

# Documentation impact

Status: required

- `docs/architecture.md`: document folder/multi-source ingestion, batch atomicity, target-centric
  reconciliation, and the source-vs-target responsibility boundary.
- `docs/design-decisions.md`: add a durable decision establishing the logical ingestion batch as
  the proposal boundary for multi-source work, one operation per target, target-specific
  provenance, and independent source/target/payload reviewability budgets while preserving
  external-agent semantic responsibility.
- `docs/data-model.md`: document multi-source proposal grounding, observed source-version binding,
  and target-specific source sets.
- `docs/generated-wiki-provenance.md`: document several source snapshots contributing in one
  reviewed generated-page mutation.
- `docs/user-manual/05-workflow.md`: explain folder ingestion and why it produces one reconciled
  proposal instead of one proposal per file.
- `docs/user-manual/14-generated-wiki-source-history.md`: explain source history for a page
  jointly grounded by several files in one ingestion batch.
- `docs/user-manual/15-mcp-exploration.md`: document the MCP-only folder exploration -> joint
  reasoning -> target-reconciled proposal workflow, exploration-time source hashes, and
  source/target/payload bounds.
- MCP tool descriptions/runtime instructions must be updated to keep the public agent contract
  synchronized with implementation.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/ingestion tests/facade tests/mcp \
  tests/proposals tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

Because this changes an externally callable MCP proposal surface, provenance semantics, and the
canonical mutation trust boundary, treat the implementation PR as security-sensitive under
`AGENTS.md`: complete the normal stabilized Codex review cycle, then request a security review,
and finish with a green full-validation checkpoint for the final material head.

## Review completion note

- Normal Codex review stabilized on `c0a3491c2f`; the final normal review reported no major issues.
- `@codex security review` was requested on the same head but did not produce a review result.
- On 2026-08-30 the user explicitly instructed the implementation agent to skip the non-working
  security-review step. This current-task user instruction overrides the repository/task workflow
  requirement for this run. No security-review result is claimed.
- The final `full-validation` checkpoint remains required after this task-state completion commit.

# Relevant decisions

- DD-001: Markdown remains canonical.
- DD-002: deterministic facts and semantic interpretation are separate.
- DD-003 / DD-004 / DD-034: consequential changes use durable proposals, explicit application,
  and stale targets fail closed.
- DD-032: proposal patches use typed operations with explicit target/base hashes.
- DD-038: canonical updates use optimistic concurrency; stale writes do not merge themselves.
- DD-079: ingestion is MCP-only and semantic synthesis remains external-agent work.
- DD-081: ingestion proposal operations are ownership-aware before publication.
- DD-083: immutable review diffs are digest-bound history.
- DD-084: source taxonomy is evidence and canonical tags are proposal-reviewed.
- DD-086: wiki structure emerges while mutation boundaries stay strict; the current preferred
  compounding contract supports one source -> several distinct targets.
- DD-087: folder location supplies semantic context rather than mutation permission.
- DD-090: stable note identity, current path, and content version are separate review facts.
- DD-092: multi-source ingestion batches evidence once and reconciles by target.
- LIFEOS-1628: generated wiki pages already support cumulative provenance from several accepted
  source snapshots over time.
- LIFEOS-1632: current compounding ingestion supports one registered source -> 1..12 distinct
  target operations in one atomic draft.
- LIFEOS-1638: ingestion proposal tools automatically refresh disposable registry state before
  source verification; refresh cannot replace an explicit exploration-time source observation.
- LIFEOS-1639: MCP exploration is broad/composable while mutation remains narrow and controlled.
- LIFEOS-1643: cross-device/stable-identity work preserves target identity and stale-review
  boundaries without silently retargeting proposals.
