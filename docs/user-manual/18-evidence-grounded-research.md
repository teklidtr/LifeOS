[← Previous: Home-Node Runtime Safety](17-home-node-runtime-safety.md) · [Manual home](README.md)

# 18. Evidence-Grounded Research

LifeOS can help an external agent research a question without turning every question into a note
or letting web claims jump directly into the wiki.

## Normal workflow

1. The agent starts with `research_query_context` or composes `vault_context`, `wiki_search`,
   and explicit read/exploration tools.
2. LifeOS returns existing canonical evidence. This step is read-only.
3. The agent decides whether the vault already contains enough evidence.
4. If the answer is already represented, the agent answers and writes nothing.
5. If an important evidence gap remains, the agent researches outside LifeOS using the tools
   available in its own provider/environment.
6. The agent submits only selected evidence through `research_capture_evidence`.
7. LifeOS stores or reuses a hash-bound source snapshot under `raw/research/` and records why it
   was acquired.
8. The agent can inspect/retrieve that new raw source and use the normal ingestion proposal tools
   if the research produced genuinely reusable durable knowledge.
9. If there is no durable novelty, no wiki proposal is needed.
10. Any durable synthesis remains a normal draft proposal until the ordinary explicit review and
    lifecycle steps are requested.

## What LifeOS does not do

LifeOS core does not contain a browser, crawler, public-web search provider, academic-search
credential, or hidden research agent. The external agent performs research.

There is also no generic MCP filesystem write tool. `research_capture_evidence` can create or
reuse only the specific canonical research-source artifact defined by LifeOS.

## Why capture before synthesis?

A captured research source records:

- source locator such as URL or DOI when available;
- external source title, author, and publisher when known;
- immutable evidence snapshot hash;
- trusted LifeOS capture actor;
- capture time;
- the query/conversation reference when available;
- `research_reason`, which explains why the evidence was acquired;
- optional agent-authored research context, kept separate from external evidence text.

This means a later proposal can point to the exact raw source, and the raw source can explain
both where the evidence came from and why it entered LifeOS.

## Duplicate and changed sources

Capturing the same source snapshot again does not create another copy. A genuinely different
research reason may add another acquisition-lineage record to the same snapshot.

If the external source content changes, LifeOS keeps the previous snapshot and creates a
different hash-bound artifact. Research history therefore does not silently rewrite itself.

## Actor, author, and ownership are different

`source_author` identifies who authored the external source. `captured_by` identifies which
trusted LifeOS actor persisted it. Generated ownership is LifeOS authorization for generated
canonical targets. None of these fields substitutes for another.

The MCP client cannot supply `captured_by`; LifeOS derives it from the trusted local or
authenticated runtime actor.

## Zero-write answers are normal

Research is not successful only when it creates a wiki page. Common valid outcomes include:

- existing LifeOS knowledge already answers the question, so nothing is written;
- external evidence is captured for traceability but confirms existing durable knowledge, so no
  wiki proposal is created;
- research produces a reusable comparison, synthesis, contradiction, or durable update, so an
  ordinary reviewed proposal is created.

External evidence alone never authorizes an automatic wiki edit.

---

[← Previous: Home-Node Runtime Safety](17-home-node-runtime-safety.md) · [Manual home](README.md)
