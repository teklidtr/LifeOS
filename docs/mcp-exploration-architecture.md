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

MCP adapters do not own vault business rules. They map type-strict inputs to facade requests,
mark MCP reads as external disclosure, record bounded disposable activity metadata, translate
deterministic validation failures, and map facade results back to structured MCP output.

This composition keeps future transports independent from the business rules. A later local
network or home-node transport can expose the same Python capabilities without reimplementing
vault access, privacy, or mutation semantics.

## Exploration primitives

The runtime adds four composable read-only operations:

- `vault_list`: bounded recursive discovery of canonical Markdown files and their folder paths;
- `vault_search`: bounded lexical search across canonical Markdown, optionally narrowed by a
  vault-relative prefix, with parser diagnostics for omitted allowed notes;
- `vault_read_many`: comparison of up to eight explicitly selected Markdown notes under one
  Markdown-body character budget with separately bounded metadata;
- `vault_links`: bounded, continuable outgoing-link and backlink discovery from current canonical
  Markdown.

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

## Path, policy, and external-disclosure boundary

The complete user-facing MCP read surface enforces the canonical retrieval policy in external
mode. This includes focused single-note reads, focused/lexical context assembly, broad
exploration, link traversal, instruction discovery, `wiki_search`, and the composed
`research_query_context` surface. Excluded prefixes remain unavailable. Protected prefixes are
default-deny. `allow_protected=true` records explicit request intent on the exploration surfaces
that support it, but protected content can cross the MCP boundary only when the canonical policy
also matches the path through `external_allowed_prefixes`.

Policy filtering occurs before denied Markdown or YAML content is opened or decoded and before
lexical ranking and result caps. Disallowed candidates therefore cannot influence allowed
results, crowd them out of bounded search/context, break an allowed query with invalid UTF-8, or
leak their paths through diagnostics.

The canonical `system/retrieval-policy.yml` is itself loaded through descriptor-based,
symlink-safe vault I/O. Missing policy uses the documented defaults; a symlink, unsafe file type,
unreadable file, invalid UTF-8, malformed YAML, or invalid schema fails closed instead of being
followed or treated as an absent policy.

Context instruction discovery first enumerates eligible YAML paths without opening them, then
reads only allowed candidates. The allowlisted `system/instructions.yml` source is subject to the
same retrieval filter before it is opened.

Secure vault traversal still enforces vault-root containment and rejects host-absolute paths,
traversal, hidden runtime directories, unsafe file types, and symlink escapes. Errors caused by
an allowed relative path retain bounded execution diagnostics; denied or host-absolute paths are
not disclosed. Protected-read eligibility grants no write, proposal, ownership, or lifecycle
authority.

## Validation and execution errors

MCP exploration argument models use strict type validation as well as the deterministic facade
validators. JSON strings are therefore not coerced into numeric limits and string values such as
`"yes"` cannot become `allow_protected=true`.

Invalid caller arguments are reported as validation errors. Once a request has passed validation
and policy eligibility, vault I/O failures such as invalid UTF-8, concurrent change, or an unsafe
allowed symlink are execution errors rather than being mislabeled as bad arguments.

Lexical search can omit an allowed note when deterministic Markdown parsing reports structural
findings. `vault_search` returns bounded parser diagnostics with the result so an MCP-only caller
can distinguish “no matching note” from “a matching candidate was omitted as malformed.”

## Output bounds and continuation

Exploration operations expose explicit bounds rather than returning an unbounded vault dump:

- `vault_list`: at most 200 entries per request;
- `vault_search`: at most 50 returned hits plus bounded parser diagnostics;
- `vault_read_many`: at most eight paths and at most 100,000 returned Markdown-body characters;
  title metadata is independently capped so it cannot bypass that bound;
- `vault_links`: at most 100 references per request.

`vault_list` uses deterministic path ordering. When a page is truncated it returns `next_after`;
passing that value back as `after` continues after the last returned path. `vault_links` uses a
deterministic link ordering and returns `next_offset` when truncated; passing that value back as
`offset` continues the same result set. This keeps both discovery surfaces traversable without
requiring an MCP client to guess omitted names.

## Canonical link resolution

`vault_links` preserves the syntax kind of each reference before canonical resolution. Normal
Markdown links and Obsidian wikilinks therefore do not share a heuristic that can reverse their
meaning:

- a relative Markdown link resolves relative to its source note, even when a vault-root path with
  the same suffix exists;
- a leading-slash Markdown target is interpreted as an explicit canonical vault path;
- a path-qualified wikilink is interpreted as a canonical vault path, not source-relative;
- a basename wikilink such as `[[topic]]` may resolve by basename only when exactly one allowed
  canonical Markdown path has that basename.

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

## Evidence-grounded research extension

LIFEOS-1641 adds two narrow MCP capabilities without adding a browser, crawler, provider
credential store, or generic canonical-write surface to LifeOS:

- `research_query_context` composes the existing policy-aware Context Pack and durable-wiki search
  surfaces in external-disclosure mode. It is read-only, uses the configured runtime directory,
  and persists no query, answer, raw source, conversation, or proposal merely because a question
  was asked.
- `research_capture_evidence` accepts one selected external evidence snapshot plus source metadata
  and acquisition context. The caller cannot supply a target path or `captured_by`; LifeOS derives
  the canonical `raw/research/` path from source/snapshot hashes and derives the actor from the
  trusted MCP request/local runtime context.

The external agent remains responsible for obtaining and interpreting outside evidence in its own
provider environment. The safe transition is:

```text
external agent research
  ↓
research_capture_evidence
  ↓
hash-bound raw/research snapshot + acquisition lineage
  ↓
normal registry preflight / source-hash verification
  ↓
existing ingestion proposal tool, only if durable novelty exists
```

`source_author` and `source_publisher` describe the external source, `captured_by` records the
trusted LifeOS actor that acquired it, and generated ownership remains a separate authorization
contract. Identical snapshots are reused, repeated acquisition lineage is idempotent, and changed
snapshots remain distinct historical evidence. Normal research workflows may add acquisition
lineage but do not replace the hash-bound evidence body.

There is no direct external-claim-to-wiki path. Captured evidence does not itself authorize a
mutation, and a question or research result that adds no reusable durable knowledge may finish
with zero proposals. When durable synthesis is justified, the existing ingestion/provenance,
ownership, review, lifecycle, and application rules remain authoritative. See
[Research Evidence Architecture](research-evidence-architecture.md).

## Derived state

Exploration does not make a second canonical index. Path discovery, lexical search, multi-read,
and current link discovery are computed from canonical Markdown through existing LifeOS
parsing/traversal primitives. Disposable registry, retrieval, graph, and activity state remain
rebuildable and non-authoritative.

## Testing contract

Deterministic tests cover both halves of the boundary:

- a real STDIO MCP client performs a multi-step list → search → multi-read → link crawl without
  direct vault filesystem access;
- MCP inputs are type-strict and cannot coerce strings into protected-read intent or limits;
- MCP reads use external disclosure policy, including `external_allowed_prefixes` for protected
  content;
- research query composition preserves external-disclosure mode and the configured runtime
  directory rather than falling back to local retrieval defaults;
- research capture has no caller-controlled `captured_by` or arbitrary vault-path field;
- retrieval policy loading rejects symlinks and other unsafe policy sources;
- policy filtering happens before Markdown/YAML reads, lexical ranking, and caps;
- protected malformed YAML/Markdown cannot break or leak through allowed context/search;
- truncated path and link discovery can continue deterministically;
- allowed-path I/O failures remain execution errors with bounded relative-path diagnostics;
- malformed allowed search candidates surface parser diagnostics rather than disappearing
  silently;
- Markdown and wikilink syntax retain distinct canonical-resolution semantics;
- oversized multi-read title metadata is separately bounded;
- exploration tools are advertised as read-only, non-destructive, idempotent, and closed-world;
- the runtime exposes no generic canonical filesystem mutation tool;
- the existing proposal application surface remains explicitly destructive and authorized.
