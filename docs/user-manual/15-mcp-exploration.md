[← Previous: Generated Wiki Source History](14-generated-wiki-source-history.md) · [Manual home](README.md)

# 15. MCP Exploration and Controlled Mutation

LifeOS-connected agents do not need unrestricted shell or filesystem access to explore the
vault. The MCP runtime provides bounded vault-native operations that can be composed into the
same iterative workflow an agent would otherwise build from `find`, `grep`, and `cat`.

The governing rule is simple: **exploration is broad; mutation is constrained**.

## 15.1 Explore iteratively

A useful agent workflow is:

1. Call `vault_list` to discover canonical Markdown paths in a relevant area. If it returns
   `truncated=true`, continue with `after=<next_after>` until the relevant listing is complete.
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

Listings use stable path ordering. When `truncated=true`, the response includes `next_after`.
Pass that exact value back as `after` to continue after the final entry in the current page.
This lets an MCP-only agent enumerate a large flat folder without already knowing omitted names.

### `vault_search`

Runs deterministic lexical search across canonical Markdown rather than only `wiki/`. The
response includes paths, titles, descriptions, excerpts, scores, and matched terms. `prefix`
can narrow the search. The default limit is 20 and the hard maximum is 50.

Retrieval-policy eligibility is applied before ranking and the result limit, so hidden or
excluded candidates cannot crowd an allowed result out of a bounded search. Use `wiki_search`
instead when deliberately searching only durable wiki knowledge.

### `vault_read_many`

Reads one to eight explicitly selected Markdown notes under one total output budget. The default
budget is 40,000 characters and the hard maximum is 100,000. Each returned item includes its
canonical path, title, current content hash, Markdown body, and truncation state.

This is useful for side-by-side comparison after search or link traversal. It is not a request
to dump the whole vault.

### `vault_links`

Returns bounded outgoing references, backlinks, or both for one canonical Markdown path. The
default limit is 50 and the hard maximum is 100.

Obsidian wikilinks that omit a folder, such as `[[topic]]`, resolve to a canonical vault path
only when the basename is unique among allowed Markdown paths. Ambiguous or unresolved targets
are not guessed. The same resolution is used for backlink discovery.

## 15.3 Protected scopes

The complete user-facing MCP read surface reuses the retrieval privacy policy. Excluded paths
remain unavailable. Protected prefixes are hidden by default from broad discovery/search,
focused `vault_read_markdown` reads, and `vault_context` source selection.

Tools that expose `allow_protected` should receive `true` only when **you explicitly asked the
agent to include a protected scope**. It expands read eligibility for that request only. It does
not authorize any canonical edit. `wiki_search` is also policy-filtered and does not provide a
protected-scope bypass.

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
page = vault_list(prefix="study/driving-licence")
while page.truncated:
    page = vault_list(prefix="study/driving-licence", after=page.next_after)
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
