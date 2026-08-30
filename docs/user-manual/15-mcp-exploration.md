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
   Inspect any returned diagnostics before assuming an empty or partial hit set is complete.
3. Read one note with `vault_read_markdown`, or compare up to eight selected notes with
   `vault_read_many`.
4. Call `vault_links` to follow outgoing references or backlinks and discover adjacent notes. If
   it returns `truncated=true`, continue with `offset=<next_offset>`. Inspect diagnostics before
   treating a backlink set as complete.
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
Allowed-path traversal failures remain explicit bounded errors; denied paths are pruned before
file inspection or decoding.

### `vault_search`

Runs deterministic lexical search across canonical Markdown rather than only `wiki/`. The
response includes paths, titles, descriptions, excerpts, scores, matched terms, and bounded
parser diagnostics for allowed notes that had to be omitted. `prefix` can narrow the search. The
default limit is 20 and the hard maximum is 50. Returned titles are capped at 512 characters and
descriptions at 1,024 characters so oversized frontmatter cannot defeat the bounded MCP response.

Retrieval-policy eligibility is applied before file decoding, ranking, and the result limit, so
hidden or excluded candidates cannot crowd an allowed result out of a bounded search or leak
through diagnostics. An allowed-path I/O failure is reported as an execution failure rather than
being mislabeled as invalid search arguments. Use `wiki_search` instead when deliberately
searching only durable wiki knowledge.

### `vault_read_many`

Reads one to eight explicitly selected Markdown notes under one total Markdown-body budget. The
default body budget is 40,000 characters and the hard maximum is 100,000. Each returned item
includes its canonical path, a separately bounded title, current content hash, Markdown body,
and truncation state. Oversized title metadata is capped rather than bypassing the body budget.

This is useful for side-by-side comparison after search or link traversal. It is not a request
to dump the whole vault.

### `vault_links`

Returns bounded outgoing references, backlinks, or both for one canonical Markdown path. The
default limit is 50 and the hard maximum is 100. Results use deterministic ordering. When
`truncated=true`, the response includes `next_offset`; pass it back as `offset` to continue.

Normal Markdown links and Obsidian wikilinks retain different resolution rules. A relative
Markdown link whose destination is `concepts/topic.md` resolves relative to the source note even
when a vault-root path with the same suffix also exists. A path-qualified wikilink is interpreted
as a canonical vault path, not silently reinterpreted as source-relative. A basename wikilink
such as `[[topic]]` resolves only when exactly one allowed canonical Markdown path has that
basename. Ambiguous or unresolved targets are not guessed. The same canonicalized target is used
for backlink discovery.

Backlink and `both` scans also return bounded diagnostics when an otherwise allowed candidate
cannot be read or structurally parsed. Such a diagnostic means the returned backlink set may be
incomplete; the failure is no longer silently indistinguishable from “no backlink”. Diagnostic
output itself is capped so malformed vault state cannot create an unbounded response.

## 15.3 Protected scopes and external disclosure

The complete user-facing MCP read surface reuses the retrieval privacy policy as an **external
disclosure boundary**. Excluded paths remain unavailable. Protected prefixes are hidden by
default from broad discovery/search, focused `vault_read_markdown` reads, link traversal, and
`vault_context` source or instruction selection.

Tools that expose `allow_protected` should receive `true` only when **you explicitly asked the
agent to include a protected scope**. That explicit request is necessary but not sufficient for
MCP disclosure: the protected path must also match `external_allowed_prefixes` in
`system/retrieval-policy.yml`. Without both conditions, the MCP read fails closed. Protected-read
eligibility never grants canonical edit authority.

A protected read grant applies only to that request. `runtime_activity` therefore re-applies the
current external retrieval policy with protected access disabled before returning any path fields.
A protected path may exist in disposable activity state for debugging provenance after an
explicitly authorized read, but a later activity call cannot use that record to rediscover the
protected path name. Public allowed path metadata remains visible.

Retrieval policy itself is read through the same symlink-safe vault I/O boundary. A policy file
that is a symlink, unsafe file type, unreadable file, invalid UTF-8, or invalid YAML is rejected
rather than treated as a permissive or absent policy. Context instruction discovery also applies
retrieval policy before descending into or decoding YAML candidates, so denied instruction-like
files cannot influence output or diagnostics.

MCP input models are type-strict. JSON strings or booleans are not coerced into numeric limits,
and string values such as `"yes"` are not coerced into `allow_protected=true`.

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

## 15.5 Folder and multi-source ingestion

When you ask an MCP-connected agent to ingest a folder, the folder is the **exploration scope**,
not a command to create one proposal for every file. The preferred workflow is:

```text
vault_list / vault_search
  ↓ discover eligible source paths in the requested area
vault_read_many
  ↓ read selected evidence and retain each exact path + content_hash snapshot
vault_context + wiki_search + relevant wiki reads
  ↓ understand context and existing durable knowledge
external agent reasons over the observed source versions together
  ↓ reconcile desired changes by target_path
ingestion_evolve_wiki_batch_proposal(source_snapshots=[...])
  ↓ one reviewed atomic draft, or no call when there is no durable delta
```

For the selected **ingestion evidence**, use `vault_read_many` so the agent receives both the
Markdown body and its current `content_hash`. The batch tool accepts an ordered set of those
observed `{path, content_hash}` source snapshots plus target-centric mutations. It does not accept
bare source paths and then decide which later source version the agent must have meant. A registry
refresh may discover newer filesystem state, but it cannot silently advance the evidence version
behind an already-synthesized candidate. If any current registered source no longer matches the
hash the agent actually read, the entire draft is refused; the agent must reread that source and
reason again from the new bytes.

Each target mutation names only the selected source paths whose supplied snapshots actually
ground that target. Several exact sections of one human-owned Wiki file may therefore be
reconciled into one file-level patch, and several selected sources may jointly ground one
generated page without attaching unrelated batch sources to that page's provenance. When a
generated taxonomy change includes a tag rationale, the rationale remains visible in the
review-digest-bound proposal instead of disappearing after input validation.

The initial safety/workload limits are independent:

- at most **64 distinct source snapshots** in one logical batch;
- at most **32 distinct target operations** in the resulting proposal;
- at most **2 MiB** for the serialized canonical `patches.json` plus immutable `review.json`
  payload.

Crossing any limit refuses the batch. LifeOS does **not** silently split an oversized folder into
several proposals, because independent drafts that overlap the same target would recreate the
stale-proposal conflict this workflow is designed to avoid. Narrow the source selection or make a
later explicit batch instead.

Every selected source is independently checked for containment, external retrieval policy,
registration, safe readability, runtime exclusion, and exact observed hash before publication.
`proposals/` and `conversations/` remain internal MCP ingestion-source scopes and are rejected in
the same way as the existing source-scoped ingestion tools. LifeOS re-verifies the observed
source snapshots immediately before persisting the draft. One invalid or changed source aborts
the whole batch. A target that changes while its immutable review snapshot is being built is
reported as a stale/conflicting batch rather than as an opaque internal error. Target application
remains ordinary proposal application: if one reviewed target has become stale, preflight
prevents partial publication of the other target operations.

Zero durable changes is still a successful outcome. The agent should simply explain that the
folder did not warrant a reusable knowledge change and create no proposal.

## 15.6 Example crawl

For a question about driving-licence study material, an MCP-connected agent might:

```text
page = vault_list(prefix="study/driving-licence")
while page.truncated:
    page = vault_list(prefix="study/driving-licence", after=page.next_after)
  ↓
search = vault_search(query="right of way")
inspect search.diagnostics when present
  ↓
observed = vault_read_many(paths=[study hit, relevant source hit])
  ↓
links = vault_links(path="wiki/right-of-way.md", direction="both")
inspect links.diagnostics when present
while links.truncated:
    links = vault_links(
        path="wiki/right-of-way.md",
        direction="both",
        offset=links.next_offset,
    )
  ↓
vault_context(question="What matters for the exam?", focus_paths=[study hit])
  ↓
ingestion_evolve_wiki_batch_proposal(
    source_snapshots=[
        {"path": item.path, "content_hash": item.content_hash}
        for item in observed.items
        if item is selected evidence
    ],
    creates=[...],
    updates=[...],
)
```

The agent can search again, follow another reference, or stop. If a selected source changed after
`observed` was read, the batch call fails rather than attributing the old synthesis to the new
bytes; reread and reconsider the evidence. If it proposes a durable change, the normal proposal
boundary applies.

## 15.7 Local STDIO remains the runtime

This feature expands the capability surface, not the transport boundary. The supported MCP
runtime remains the local STDIO server configured for a specific vault and trusted actor. A
network-accessible or always-on home-node transport is separate work and must reuse the same
Python contracts rather than reimplementing them.

---

[← Previous: Generated Wiki Source History](14-generated-wiki-source-history.md) · [Manual home](README.md)
