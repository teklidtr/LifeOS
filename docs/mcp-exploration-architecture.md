# MCP Exploration and Controlled Mutation Architecture

## Principle

LifeOS constrains mutation, not exploration.

An external agent should be able to inspect enough canonical vault state to decide what is
relevant, what to read next, and whether any durable change is justified. LifeOS owns the
security and mutation boundary, not the semantic decision.

This preserves the existing split:

- canonical Markdown remains the source of truth;
- Python establishes deterministic facts and enforces path, privacy, ownership, provenance,
  proposal, and authorization rules;
- the external agent interprets meaning and chooses the next read or proposed change;
- consequential canonical changes remain explicit and reviewable.

## Runtime composition

The user-facing STDIO MCP runtime starts from the existing core server and then composes the
exploration surface. The core still owns registry maintenance, ingestion proposals, proposal
lifecycle, and runtime diagnostics. The user-facing runtime replaces the legacy
`vault_read_markdown` and `vault_context` entries with policy-aware adapters over the same
facades, then adds the four exploration primitives.

MCP adapters do not own vault business rules. They map typed inputs to facade requests, record
bounded disposable activity metadata, translate deterministic validation failures, and map
facade results back to structured MCP output.

This composition keeps future transports independent from the business rules. A later local
network or home-node transport can expose the same Python capabilities without reimplementing
vault access, privacy, or mutation semantics.

## Exploration primitives

The runtime adds four composable read-only operations:

- `vault_list`: bounded recursive discovery of canonical Markdown files and their folder paths;
- `vault_search`: bounded lexical search across canonical Markdown, optionally narrowed by a
  vault-relative prefix;
- `vault_read_many`: comparison of up to eight explicitly selected Markdown notes under one
  total character budget;
- `vault_links`: bounded outgoing-link and backlink discovery from current canonical Markdown.

They complement policy-aware runtime reads:

- `vault_read_markdown` for a focused single-note read;
- `wiki_search` for wiki-specific lexical search;
- `vault_context` for instruction-aware pre-reasoning context;
- semantic retrieval and knowledge-conversation facilities where their derived index is in use.

The intended control loop is iterative:

```text
list/search
  ↓
read one or several results
  ↓
follow references or refine the query
  ↓
inspect context
  ↓
decide whether zero or more durable changes are worth proposing
```

There is deliberately no MCP operation equivalent to arbitrary shell `find`, `grep`, or `cat`
against the host filesystem. LifeOS supplies the useful vault-scoped capability directly.

## Path and privacy boundary

The complete user-facing read surface enforces the canonical retrieval policy. This includes
focused single-note reads and focused/lexical context assembly, not only the newly added broad
exploration tools. Excluded prefixes remain unavailable. Protected prefixes are default-deny;
tools that support protected reads require an explicit `allow_protected=true` request, and the
runtime instructs clients to use that only when the user explicitly asks to include a protected
scope.

Policy filtering occurs before lexical ranking and result caps. Disallowed candidates therefore
cannot crowd allowed results out of a bounded search or context pack.

Secure vault traversal still enforces vault-root containment and rejects host-absolute paths,
traversal, hidden runtime directories, unsafe file types, and symlink escapes. Protected-read
eligibility grants no write, proposal, ownership, or lifecycle authority.

## Output bounds and continuation

Exploration operations expose explicit bounds rather than returning an unbounded vault dump:

- `vault_list`: at most 200 entries per request;
- `vault_search`: at most 50 returned hits;
- `vault_read_many`: at most eight paths and at most 100,000 returned Markdown characters;
- `vault_links`: at most 100 references per request.

`vault_list` uses deterministic path ordering. When a page is truncated it returns `next_after`;
passing that value back as `after` continues after the last returned path. Other bounded results
report truncation where applicable.

## Canonical link resolution

`vault_links` compares references against the allowed canonical path set. Explicit canonical
paths win. An Obsidian wikilink that omits its folder, such as `[[topic]]`, may fall back to
basename resolution only when exactly one allowed canonical Markdown path has that basename.
Ambiguous or unresolved targets are not guessed. The same canonicalized target is used for
outgoing links and backlink comparisons.

## Mutation boundary

No generic canonical `write_file`, `delete_file`, `move_file`, host shell, or equivalent MCP
surface is introduced.

Agent-generated canonical changes continue to use LifeOS-native contracts:

```text
agent reasoning
  ↓
bounded proposal-producing tool
  ↓
draft proposal + immutable review snapshot
  ↓
explicit submit
  ↓
explicit approval / trusted authorization
  ↓
validated application
```

Ownership, source hashes, target hashes, provenance, operation budgets, recovery, and atomic
application remain authoritative. Broad read capability therefore does not weaken the existing
strict mutation boundary.

## Derived state

Exploration does not make a second canonical index. Path discovery, lexical search, multi-read,
and current link discovery are computed from canonical Markdown through existing LifeOS
parsing/traversal primitives. Disposable registry, retrieval, graph, and activity state remain
rebuildable and non-authoritative.

## Testing contract

Deterministic tests cover both halves of the boundary:

- a real STDIO MCP client performs a multi-step list → search → multi-read → link crawl without
  direct vault filesystem access;
- legacy focused reads and context cannot bypass protected-scope default-deny behavior;
- policy filtering happens before lexical ranking/capping, including when more than 200
  protected candidates score above an allowed match;
- truncated path discovery can continue deterministically without guessing sibling names;
- invalid bounded exploration arguments are reported as tool argument errors rather than
  internal failures;
- unique basename wikilinks resolve to canonical paths while ambiguous basenames are not guessed;
- exploration tools are advertised as read-only, non-destructive, idempotent, and closed-world;
- the runtime exposes no generic canonical filesystem mutation tool;
- the existing proposal application surface remains explicitly destructive and authorized.
