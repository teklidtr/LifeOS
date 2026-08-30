---
id: LIFEOS-1641
title: Add evidence-grounded query research and durable synthesis pipeline
status: ready
phase: 16
depends_on:
  - LIFEOS-1639
risk: high
---

# Goal

Add a first-class agent-facing query pipeline that can answer from existing LifeOS knowledge,
detect when evidence is insufficient, acquire external evidence through the external agent,
preserve that evidence in `raw/` with complete acquisition provenance, ingest it through the
normal LifeOS knowledge workflow, and persist only genuinely durable new synthesis.

The pipeline should make research compound without turning every question or answer into a
new wiki page and without allowing uncited web claims to jump directly into canonical durable
knowledge.

A durable principle for this workflow is:

> External evidence should preserve not only where it came from, but why LifeOS acquired it.

# Design principles

- Querying existing knowledge is read-only by default.
- A query is not persisted merely because it was asked.
- Existing wiki/raw knowledge should be reused instead of duplicated.
- External research is performed by the external agent/provider environment, not by an LLM,
  browser, or web-search runtime embedded inside LifeOS.
- New external evidence enters through a typed `raw/` evidence-capture boundary before it can
  ground durable wiki evolution.
- Source identity, capture actor, source authorship, and ownership/authority are separate
  concepts and must not be conflated.
- The external evidence snapshot is hash-bound and should not become freely rewritable agent
  prose after capture.
- Durable synthesis is proposed only when the query/research produced reusable knowledge not
  already represented in the wiki.
- Wiki mutation continues to use the existing proposal, provenance, ownership, lifecycle, and
  stale-target rules.

# Scope

- Define a typed query/research orchestration contract that supports the following semantic
  flow without placing agent reasoning inside LifeOS:

  ```text
  user query
      -> retrieve/contextualize existing LifeOS knowledge
      -> external agent reasons over evidence
      -> if evidence is sufficient: answer
      -> if an evidence gap matters: external agent researches
      -> capture selected external evidence into raw/
      -> normal LifeOS ingestion/retrieval against the new source
      -> answer/synthesize
      -> if durable novelty exists: create a reviewed proposal
      -> otherwise persist no duplicate wiki knowledge
  ```

- Reuse the completed semantic-retrieval and knowledge-conversation subsystems from
  LIFEOS-1400 through LIFEOS-1411 rather than creating a second RAG/conversation engine.
- Define a controlled research-source capture primitive suitable for MCP/external agents. It
  may create a new canonical `raw/` evidence artifact but must not expose arbitrary canonical
  write, overwrite, move, or delete behavior.
- Define canonical metadata/lineage for externally acquired research evidence. At minimum,
  preserve:
  - external source locator such as URL/DOI when available;
  - source title and source author/publisher when known;
  - retrieval/capture timestamp;
  - content/source hash for the captured snapshot;
  - server-authoritative `captured_by` actor identity rather than a spoofable caller field;
  - origin kind and an originating query/conversation reference when one exists;
  - a concise `research_reason` describing the evidence gap or question that caused the
    source to be collected;
  - the distinction between external evidence text and agent-authored research context.
- Keep external source authorship separate from LifeOS actor attribution and from generated
  ownership authorization.
- Make the captured evidence snapshot immutable/hash-bound for normal agent workflows.
  Metadata corrections or lineage additions must use a controlled typed operation and may not
  silently replace the captured source bytes/text.
- Define deterministic identity/deduplication for repeated acquisition of the same source
  snapshot. Re-capturing identical evidence should not create duplicate raw evidence merely
  because a second query encountered it; distinct acquisition reasons may be linked
  idempotently to the same evidence snapshot.
- Preserve changed external snapshots as distinct historical evidence when content changes,
  rather than silently replacing the prior snapshot.
- Connect captured research evidence to the existing ingestion pipeline so normal registry
  preflight, source hash, provenance, wiki search/context, proposal, ownership, and application
  semantics remain authoritative.
- Define a durable-novelty decision boundary for query outcomes:
  - an answer already represented in existing durable knowledge produces no wiki proposal;
  - a reusable comparison, connection, synthesis, contradiction, or other durable delta may
    produce a proposal;
  - external evidence alone does not authorize a wiki mutation.
- Preserve end-to-end lineage so a future durable claim can be traced from wiki/proposal
  provenance back to the raw evidence and, where available, to the query/conversation and
  reason the evidence was acquired.
- Expose the necessary typed capabilities through MCP after LIFEOS-1639 establishes the
  exploration/mutation surface. Reuse existing bridge/conversation services where appropriate
  instead of implementing two business-rule engines.
- Add deterministic integration tests for sufficient-evidence, evidence-gap, duplicate-source,
  changed-source, no-durable-novelty, and durable-synthesis paths without an LLM in the test
  loop.

# Out of scope

- Embedding an LLM, browser, crawler, web search engine, academic search provider, or provider
  credentials inside LifeOS.
- Automatically browsing the public web from LifeOS core.
- Persisting every query, answer, context pack, or model response as durable wiki knowledge.
- Allowing web claims to bypass `raw/` evidence capture and normal ingestion provenance.
- Giving agents unrestricted filesystem or shell write access to `raw/` or the rest of the
  vault.
- Treating `captured_by` as the author of the external source or as ownership of its claims.
- Replacing the completed LIFEOS-1400..1411 retrieval/conversation/proposal functionality.
- Automatically approving or applying synthesis proposals.

# Acceptance criteria

- A query whose answer is already represented in LifeOS can be answered without creating a
  duplicate raw source or wiki proposal.
- When the external agent identifies a material evidence gap, it can submit selected external
  evidence through a typed LifeOS capture operation that creates or reuses a canonical raw
  evidence artifact.
- Every research-source artifact records where the evidence came from, who/which actor
  captured it, why it was acquired, when it was captured, and the immutable snapshot hash.
- `captured_by`, external `source_author`, and ownership/authority remain separate fields and
  semantics; actor identity is server-authoritative.
- Identical source snapshots are deduplicated deterministically while allowing multiple
  query/research-reason lineage links; changed snapshots preserve history.
- A captured external source cannot be silently overwritten through the normal agent-facing
  research workflow.
- New external evidence enters the normal registry/ingestion/provenance path before it can
  ground durable wiki evolution.
- Durable synthesis is proposed only when it represents a real reusable delta not already
  present in the wiki; no-delta query/research runs may finish with zero proposals.
- Proposal provenance can be traced to the exact raw source snapshot(s), and raw research
  provenance can be traced to the originating query/conversation when such a reference exists.
- Existing LIFEOS-1400..1411 retrieval/conversation capabilities are composed rather than
  forked, and existing ingestion ownership/provenance rules remain authoritative.
- MCP integration exposes the controlled research workflow without adding arbitrary vault
  mutation tools.
- Deterministic tests cover the full pipeline without a network dependency or LLM-quality
  assertion.

# Documentation impact

Status: required

- `docs/architecture.md`: document the query -> evidence-gap -> external research -> raw ->
  ingestion -> durable-synthesis boundary and authority model.
- `docs/data-model.md`: document the research-source/acquisition-lineage fields if a new
  canonical artifact or metadata contract is introduced.
- `docs/user-manual/03-feature-breakdown.md`: explain evidence-grounded agent research and
  why external sources are captured before durable knowledge changes.
- `docs/user-manual/05-workflow.md`: document the normal query/research workflow, including
  zero-write answers and durable-novelty proposals.
- Relevant MCP/retrieval/conversation documentation must describe research-source capture and
  the no-direct-web-to-wiki rule.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/retrieval tests/conversations tests/ingestion tests/mcp tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- LIFEOS-1639: MCP should provide rich exploration while constraining canonical mutation.
- LIFEOS-1400 through LIFEOS-1411: semantic retrieval, knowledge conversations, grounded
  answers, citations, conversation artifacts, and proposal conversion already exist and must
  be reused.
- DD-033: disposable runtime/index state must not become the only home of provenance.
- DD-035: generated ownership remains canonical authorization data and must not be confused
  with source authorship or capture attribution.
- DD-036: Python remains the sole LifeOS business-rule engine.
- DD-060: semantic retrieval composes lexical, metadata, links, and graph signals rather than
  replacing canonical navigation.
- DD-061: retrieval chunks, embeddings, and ranking state remain disposable/rebuildable.
- DD-062: protected retrieval scopes fail closed.
- DD-063: saved knowledge conversations are canonical Markdown artifacts.
- DD-064: citation/evidence validation remains deterministic and hash-bound.
- DD-065: conversation outcomes become proposals rather than silent mutations.
- DD-066: provider-backed retrieval/answers remain optional and provider-neutral.
- Existing ingestion source-hash and incremental provenance contracts remain authoritative.
