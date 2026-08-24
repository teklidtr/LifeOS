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

The user-facing STDIO MCP runtime composes two surfaces:

1. the existing core server, which owns registry maintenance, context, ingestion proposals,
   proposal lifecycle, and runtime diagnostics;
2. a read-only exploration adapter over the LifeOS exploration facade.

The exploration adapter does not implement vault business rules. It maps typed MCP inputs to
facade requests, records bounded disposable activity metadata, and maps facade results back to
structured MCP output.

This composition keeps future transports independent from the business rules. A later local
network or home-node transport can expose the same Python capabilities without reimplementing
vault access or mutation semantics.

## Exploration primitives

The runtime adds four composable read-only operations:

- `vault_list`: bounded recursive discovery of canonical Markdown files and their folder paths;
- `vault_search`: bounded lexical search across canonical Markdown, optionally narrowed by a
  vault-relative prefix;
- `vault_read_many`: comparison of up to eight explicitly selected Markdown notes under one
  total character budget;
- `vault_links`: bounded outgoing-link and backlink discovery from current canonical Markdown.

They complement existing tools:

- `vault_read_markdown` for a focused single-note read;
- `wiki_search` for the existing wiki-specific lexical path;
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

Exploration uses the existing secure vault traversal implementation. Host-absolute paths,
traversal, hidden runtime directories, and symlink escapes are not part of the agent-facing
contract.

The exploration facade also applies the canonical retrieval policy. Excluded prefixes remain
unavailable. Protected prefixes are default-deny and become available only when the MCP request
sets `allow_protected=true`; the server instructions tell clients to do that only when the user
explicitly asks to include a protected scope.

This flag grants read eligibility only. It grants no write, proposal, ownership, or lifecycle
authority.

## Output bounds

Exploration operations expose explicit bounds rather than returning an unbounded vault dump:

- `vault_list`: at most 200 entries per request;
- `vault_search`: at most 50 returned hits;
- `vault_read_many`: at most eight paths and at most 100,000 returned Markdown characters;
- `vault_links`: at most 100 references per request.

Defaults are lower than those hard maxima. Results expose truncation where content or path/link
lists can be cut by a requested bound.

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
- protected content is omitted by default and requires an explicit protected-read request;
- exploration tools are advertised as read-only, non-destructive, idempotent, and closed-world;
- the runtime exposes no generic canonical filesystem mutation tool;
- the existing proposal application surface remains explicitly destructive and authorized.
