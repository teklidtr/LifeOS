[← Previous: Generated Wiki Source History](14-generated-wiki-source-history.md) · [Manual home](README.md)

# 15. MCP Exploration and Controlled Mutation

LifeOS-connected agents do not need unrestricted shell or filesystem access to explore the
vault. The MCP runtime provides bounded vault-native operations that can be composed into the
same iterative workflow an agent would otherwise build from `find`, `grep`, and `cat`.

The governing rule is simple: **exploration is broad; mutation is constrained**.

## 15.1 Explore iteratively

A useful agent workflow is:

1. Call `vault_list` to discover canonical Markdown paths in a relevant area.
2. Call `vault_search` to search the whole allowed vault or narrow the query with `prefix`.
3. Read one note with `vault_read_markdown`, or compare up to eight selected notes with
   `vault_read_many`.
4. Call `vault_links` to follow outgoing references or backlinks and discover adjacent notes.
5. Use `vault_context` when goals, study purpose, journal state, experiments, or scoped
   `system/instructions.yml` rules may change how the evidence should be interpreted.
6. Use `wiki_search` when the immediate question is specifically about existing durable wiki
   knowledge.
7. Refine the search and continue reading until the agent has enough evidence to decide what,
   if anything, should change.

These operations are read-only. Calling them does not register a source, create a proposal, or
change canonical Markdown.

## 15.2 Tool reference

### `vault_list`

Discovers canonical Markdown files and their folder paths. `prefix` narrows discovery to one
vault-relative subtree. The default result limit is 100 and the hard maximum is 200.

Use it when the agent does not yet know exact filenames.

### `vault_search`

Runs deterministic lexical search across canonical Markdown rather than only `wiki/`. The
response includes paths, titles, descriptions, excerpts, scores, and matched terms. `prefix`
can narrow the search. The default limit is 20 and the hard maximum is 50.

Use `wiki_search` instead when deliberately searching only durable wiki knowledge.

### `vault_read_many`

Reads one to eight explicitly selected Markdown notes under one total output budget. The default
budget is 40,000 characters and the hard maximum is 100,000. Each returned item includes its
canonical path, title, current content hash, Markdown body, and truncation state.

This is useful for side-by-side comparison after search or link traversal. It is not a request
to dump the whole vault.

### `vault_links`

Returns bounded outgoing references, backlinks, or both for one canonical Markdown path. The
default limit is 50 and the hard maximum is 100.

Use it to continue a crawl from evidence already judged relevant rather than relying only on
keyword similarity.

## 15.3 Protected scopes

The exploration surface reuses the retrieval privacy policy. Excluded paths remain unavailable.
Protected prefixes are hidden by default.

The optional `allow_protected` request flag should be set only when **you explicitly asked the
agent to include a protected scope**. It expands read eligibility for that request only. It does
not authorize any canonical edit.

## 15.4 Mutation still uses proposals

There is no generic MCP `write_file`, `delete_file`, `move_file`, or host-shell operation for
canonical vault state.

After exploration, an agent may decide that no durable change is useful. That is a valid result.
If a durable change is justified, it must use a bounded LifeOS proposal-producing operation such
as the wiki/study ingestion proposal tools. Those tools still validate source state, target
hashes, generated ownership, provenance, operation bounds, and review snapshots.

Proposal lifecycle transitions remain separate and explicit:

```text
draft
  ↓ explicit submit
pending
  ↓ explicit approval / trusted authorization
approved
  ↓ validated apply
applied
```

Broad exploration therefore does not make the agent autonomous over canonical data.

## 15.5 Example crawl

For a question about driving-licence study material, an MCP-connected agent might:

```text
vault_list(prefix="study/driving-licence")
  ↓
vault_search(query="right of way")
  ↓
vault_read_many(paths=[study hit, relevant wiki hit])
  ↓
vault_links(path="wiki/right-of-way.md", direction="both")
  ↓
vault_context(question="What matters for the exam?", focus_paths=[study hit])
```

The agent can then search again, follow another reference, or stop. If it proposes a durable
change, the normal proposal boundary applies.

## 15.6 Local STDIO remains the runtime

This feature expands the capability surface, not the transport boundary. The supported MCP
runtime remains the local STDIO server configured for a specific vault and trusted actor. A
network-accessible or always-on home-node transport is separate work and must reuse the same
Python contracts rather than reimplementing them.

---

[← Previous: Generated Wiki Source History](14-generated-wiki-source-history.md) · [Manual home](README.md)
