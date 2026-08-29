# LifeOS Architecture

## System layers

### Markdown vault

The vault is canonical human-readable state.

Canonical areas used by the current system include:

```text
journal/
raw/
study/
wiki/
flashcards/
patterns/
profile/
goals/
plans/
experiments/
metrics/
reviews/
conversations/
captures/
attachments/
proposals/
system/
```

Not every canonical area is part of the minimal fresh-vault bootstrap. `lifeos init`
creates the core roots required by the bootstrap contract; feature-owned artifacts such as
knowledge conversations, rich captures, and attachment evidence use their own canonical
storage contracts as those features are used.

### Deterministic layer

Scripts establish facts:

- file discovery and hashes
- stable IDs and provenance
- generated-file ownership
- proposal application
- task extraction
- index generation
- link and citation validation
- graph dirty-state tracking
- structural lint

### Agent layer

Agents interpret meaning:

- classify and synthesize sources
- decompose goals
- propose wiki edits
- create flashcards
- interpret repeated avoidance
- identify candidate patterns and contradictions
- explain evidence coverage

Agents do not silently promote interpretations into truth.

LifeOS does not embed an ingestion model client or accept provider API keys. External
agents connect through the shared MCP runtime using either the local STDIO adapter or the
explicitly configured authenticated home-node Streamable HTTP adapter. Universal runtime
behavior is advertised by the MCP server; vault-specific scoped behavior is loaded only from
the allowlisted `system/instructions.yml`. Application `AGENTS.md` governs development and is
not inherited by an MCP client.

A registered canonical Markdown source may come from `raw/`, `study/`, `journal/`,
`experiments/`, `goals/`, or another ordinary vault area. Folder location supplies semantic
context rather than permission to reason. When situational context matters, `vault_context`
combines explicit focus paths, applicable vault instructions, and bounded relevant canonical
Markdown before the agent chooses mutations. A healthy disposable retrieval index supplies the
existing hybrid exact/lexical, semantic when configured, metadata, link, graph, pin, and rerank
signals; missing or stale derived state falls back to canonical deterministic lexical retrieval.
The external agent can then continue with list/search/read/link operations, search `wiki/`, read
relevant existing notes, and decide whether a source warrants zero durable changes or a bounded
set of 1..12 distinct creates and exact-section updates. Folder organization beneath `wiki/` is
agent-selected and may evolve over time; LifeOS does not prescribe an entity/concept/source/
synthesis taxonomy.

For a registered `study/` source, the same reasoning pass may additionally propose selective
flashcards. The agent decides what merits retrieval practice from the inferred learning context
(exam relevance, future prerequisites, conceptual leverage, mechanisms, confusable distinctions,
or comparable evidence). Deterministic LifeOS validates paths, source hashes, ownership,
provenance, operation budgets, immutable review snapshots, and atomic application; it does not
encode pedagogical importance. Generated creates may safely materialize bounded nested parents
beneath existing canonical `wiki/` and `flashcards/` roots. The roots themselves are never
created implicitly.

Source taxonomy is evidence, not instruction. Human-owned wiki updates remain base-hash-bound
`patch_human_file` operations; unchanged generated-owned wiki updates remain ownership/hash-bound
`replace_generated_file` operations. Orphaned ownership, generator mismatch, external
modification, unsafe paths, and malformed ownership state fail closed before publication or
application. Every proposal-producing ingestion route stops at draft unless a separate explicit
lifecycle transition is requested.

Disposable `.lifeos/activity/` records bounded MCP routing metadata for debugging, such as tool
names, request actor IDs when available, paths, applicable instruction IDs, proposal IDs,
operation counts, and changed paths. It is not canonical history and does not copy bearer
credentials, note bodies, or flashcard answers.

### Human layer

The user controls goals, proposal approval, personal interpretations, policy changes, pattern promotion, and archival decisions.

## Vault bootstrap boundary

The LifeOS application and a user's vault are separate. The first-party `lifeos init [PATH]`
command owns the minimal fresh-vault bootstrap contract in application code rather than in a
Cookiecutter/Jinja template or documentation copy. It creates the current core semantic roots,
portable `lifeos.yml`, vault-root `AGENTS.md`, allowlisted `system/instructions.yml`, canonical
`system/generated-ownership.json`, `.gitignore`, and a local Git repository.

Initialization is deliberately non-destructive. An empty or missing target may be initialized;
a recognized LifeOS vault is an idempotent no-op; a non-empty unrecognized or partial target
fails closed rather than being repaired or overwritten. A failed late bootstrap does not
recursively delete the target because concurrent user content may have appeared. External MCP,
Obsidian, Codex, Claude, shell, or other client configuration remains explicit and is never
mutated by `lifeos init`.

## Proposal engine

Consequential changes are stored under:

```text
proposals/<proposal-id>/
  proposal.md
  patches.json
  review.json
```

`patches.json` contains the authoritative ordered typed operations. New proposals
also contain a canonical, versioned `review.json` snapshot of the exact unified
diffs shown during review. The snapshot is bound to the proposal ID, canonical
patch hash, operation identities and lifecycle review digest, so applied history
does not depend on later target or ownership-manifest state. Legacy proposals
without a snapshot remain readable through an explicitly labeled live-preview
fallback. A deterministic tool applies only explicitly approved items whose
target hashes still match.

## Registry

The current SQLite registry stores deterministic file observations and source versions,
generated-output facts, indexed proposal metadata, schema migrations, and an optional derived
provenance index. It does not currently own canonical generated ownership, task bodies, graph
publications, semantic retrieval state, or full Markdown content. Canonical generated ownership
remains exclusively in `system/generated-ownership.json`.

The shared deterministic refresh facade is available as `lifeos scan` for local recovery and as
`registry_refresh` for MCP agents. Those two surfaces initialize the registry when needed and
refresh the file and proposal indexes without changing canonical Markdown or adding, repairing,
or releasing durable ownership. The provenance tables use a separate deterministic
`refresh_provenance_index()` path; `lifeos scan` does not implicitly refresh them. See
[Registry](registry.md).

## Managed content

```md
<!-- lifeos:managed:start block-name -->
Generated content
<!-- lifeos:managed:end block-name -->
```

Markers must be unique, non-nested, and paired. Creation or deletion requires proposal approval.

## Adaptive planning

Tasks stay close to plans and are globally indexed by scripts.

```text
long-term goal    broad direction
medium-term plan  clear outcome and milestones
near-term actions detailed one or two weeks ahead
today menu        selected from eligible actions
```

The planner proposes a menu rather than issuing commands.

## Adaptive feedback layer

Explicit execution outcomes are normalized into a deterministic, rebuildable
evidence dataset. Cautious duration calibration, separate energy and motivation
fit, and repeated-avoidance hypotheses may adjust the daily recommendation only
through an optional bounded policy. The original planner remains visible as the
baseline, and plan changes require proposals. See
[Adaptive-Planning Feedback Architecture](adaptive-feedback-architecture.md).

## Graph layer

Graphify is an optional helper behind a LifeOS skill.

```text
.lifeos/graphify/
  knowledge/
  provenance/
  personal-patterns/
  system/
```

Graphify supplies paths, communities, bridge nodes, and visualization. LifeOS controls inputs, stable IDs, evidence classes, validation, and proposal generation.

## Context packs

A Context Pack is the bounded context-management layer above the authoritative retrieval
subsystem. It assembles the question, validated explicit focus paths, applicable vault
instructions, bounded canonical excerpts, evidence gaps, diagnostics, omissions, and bounded
retrieval provenance. Explicit focus paths are placed first and remain present even when hybrid
ranking would prefer other notes; they still pass normal vault safety and privacy validation.
Instruction applicability is evaluated against the final selected source set and grants no
mutation authority.

When `.lifeos/retrieval/` is healthy, remaining source slots reuse the existing hybrid exact,
lexical, semantic when configured, metadata, link, optional graph, pin, rerank, deduplication,
and deterministic-ordering contracts. Context Packs do not own a parallel embedding index or
RAG stack. Machine-readable source metadata may expose retrieval mode, contributing signal
names, numeric ranking components, and duplicate paths. Those fields explain retrieval evidence
without storing or returning hidden model reasoning.

Retrieval state is disposable rather than authoritative. Missing, stale, corrupt, incompatible,
or otherwise unavailable index state causes Context Pack construction to use canonical
deterministic lexical fallback and report the degraded capability in omissions. A healthy index
without a semantic query provider still uses local hybrid signals and reports the absent semantic
capability. Protected scopes remain default-deny. Explicit protected external MCP requests use
the canonical policy-filtered lexical path until hybrid requests themselves carry external
provider-disclosure mode.

`vault_context` is therefore an initial map, not a final crawl, answer generator, or ingestion
operation. Agents can continue iteratively with `vault_list`, `vault_search`,
`vault_read_markdown`, `vault_read_many`, `vault_links`, and the deliberately lexical
`wiki_search` primitive. A context pack grants no mutation authority.

## Optional exports

Purpose-specific bundles may be generated under `.lifeos/exports/`, such as a public wiki, biology study bundle, trusted-agent bundle, or personal-review bundle. They are optional products, not mirrors of the vault.

## Obsidian desktop interaction

Obsidian is the primary human interface. A thin TypeScript plugin launches a vault-scoped
Python bridge over versioned JSON-RPC/STDIO. Python remains the sole implementation of
business rules and canonical writes. Direct UI writes use expected content hashes and
idempotency keys. Consequential agent-generated changes remain proposals with trusted
interactive authorization. The Obsidian review surface may present one **Accept changes**
action for the remaining draft-to-applied lifecycle. One digest-bound confirmation authorizes
that exact reviewed content; Python still persists each lifecycle transition, reloads and
rechecks the digest between transitions, and runs full application-time target validation.
See [Obsidian Desktop Architecture](obsidian-desktop-architecture.md).

## Adaptive feedback release architecture

Adaptive planning is shipped as a bounded layer above the baseline planner.
Canonical execution events, corrections, exclusions, mode preferences, diagnosis
dismissals, and reset boundaries remain in the Markdown vault. The normalized
evidence dataset and historical replay results are disposable.

The Obsidian Today view reads `system/adaptive-planning.yml` by default. An
explicit request may temporarily override the mode, but it does not rewrite the
canonical preference. Off returns the baseline menu, Shadow computes the
adaptive candidate while returning baseline, and Active may return the adaptive
candidate. All modes preserve baseline output for comparison.

Historical replay is read-only and prevents outcome leakage by using only events
strictly earlier than each replayed planning day. Evaluation reports separate
measures such as unused time, overflow, missing outcomes, completion fraction,
estimate error, and explanation coverage. It never combines them into a hidden
user score.

Legacy adaptive preferences require an explicit migration. Legacy enabled state
migrates to Shadow rather than Active. Unsupported future schemas fail closed.
Plan-improvement findings become ordinary Git-tracked proposals and reuse the
same validation, stale-write, authorization, application, and recovery state
machine as every other consequential change.

## Goal-to-plan copilot

The optional goal-to-plan copilot turns an explicitly selected direction into
clarification, experiment, link, park, or reviewable plan options. Readiness,
context inclusion, rolling-wave depth, portfolio fit, and proposal application
are deterministic boundaries. Model adapters only create validated suggestions.
The user previews context and edits drafts in Obsidian; canonical changes still
use the existing proposal lifecycle. See
[Goal-to-Plan Copilot Architecture](goal-to-plan-copilot-architecture.md).

Planning sessions and replanning reviews live under disposable `.lifeos/`
runtime state. Goals, plans, proposals, execution evidence, review notes, and
applied decision lineage remain canonical Markdown. Removing the runtime state
cannot remove or rewrite those canonical files, and rebuilding the index
rediscovers them.

Daily attention and weekly review may surface a planning or replanning prompt
from explicit evidence. The review is recalculated from current canonical state,
keeps the original decision lineage inspectable, suppresses only an unchanged
rejected evidence fingerprint, and creates a proposal for every consequential
change. Continue unchanged creates no proposal.

The shipped bridge exposes versioned readiness, context, session, option,
decomposition, capacity, explanation, proposal, and replanning capabilities.
The Obsidian workspace is the primary interaction surface. Provider adapters are
optional, provider-neutral, schema-bounded, and fail back to deterministic
operation when missing, invalid, or timed out.


## First-class review artifacts

Daily and weekly reviews are canonical Markdown under `reviews/daily/` and
`reviews/weekly/`. One daily artifact contains morning and evening phases; weekly
artifacts use ISO-week identity and explicit period boundaries. Managed facts,
items, continuity, and completion summaries are separated from human-owned
reflection by validated managed blocks.

Progress, prompt answers, item decisions, lifecycle events, proposal references,
snapshot lineage, and migration lineage live in frontmatter. Runtime indexes under
`.lifeos/reviews/` are disposable and rebuild from the artifacts. Review refreshes
require optimistic concurrency and preserve human Markdown byte-for-byte outside
managed blocks. External canonical changes remain draft proposals until the shared
submit, approve, and apply lifecycle completes.

The Obsidian review workspace is a thin typed client for Python bridge methods. It
opens today, the current ISO week, active artifacts, and history; handles stale and
blocked states; and exposes explicit migration preview and index rebuild actions.
Legacy source files remain untouched after migration. See
[Review Artifact Architecture](review-artifact-architecture.md) and
[First-Class Daily and Weekly Reviews](user-manual/10-first-class-reviews.md).

## Semantic retrieval and knowledge conversations

Semantic retrieval is an additional, derived discovery layer over canonical
Markdown. Structural chunks, embeddings, link tables, ranking state, and rebuild
journals live under `.lifeos/retrieval/` and use index schema version 1. A complete
rebuild writes to staging and publishes atomically; incremental synchronization
handles creates, edits, stable-ID moves, content-preserving renames, and deletes.
Missing, stale, interrupted, corrupt, and incompatible states expose explicit
recovery plans.

Hybrid ranking keeps exact, lexical, semantic, metadata, link, optional graph,
pin, and optional reranking signals separate and inspectable. Filters and
protected-scope policy run before ranking. Results preserve note path, heading,
line range, hashes, source metadata, duplicate provenance, and deterministic tie
ordering. Where a canonical note has a durable frontmatter `id`, retrieval also
exposes that stable ID beside the note's current path so agents do not mistake the
filesystem address for permanent identity. No-provider mode retains all local
non-vector signals.

The same hybrid/index/provider subsystem supplies Context Pack candidate selection; Context
Packs add focus-path precedence, final-source instruction routing, bounded gaps/omissions, and
MCP-facing retrieval provenance rather than creating another semantic index. `wiki_search`
remains intentionally lexical so an agent can compose exact durable-wiki discovery with the
initial Context Pack and subsequent explicit reads.

Knowledge conversations are canonical Markdown under `conversations/YYYY/`.
Their managed block stores scope, turns, evidence fingerprints, validated
citations, branch lineage, provider disclosure, and lifecycle state. Human-owned
annotations remain outside the managed block. Deterministic citation validation
rejects nonexistent evidence and marks changed or deleted sources stale.
Conversation outcomes create ordinary proposals with exact targets, patches,
evidence, and stale-target hashes. They never mutate another note directly. See
[Semantic Retrieval and Knowledge Conversation Architecture](semantic-retrieval-conversation-architecture.md)
and [Semantic Retrieval and Knowledge Conversations](user-manual/11-semantic-retrieval-and-knowledge-conversations.md).

## Personal experiments

Personal experiments are canonical Markdown artifacts under `experiments/YYYY/`.
The experiment application service owns schema validation, lifecycle transitions,
protocol amendments, explicit missing-data states, deterministic safety policy,
timezone-aware schedules, observations, descriptive analysis, lineage, migration,
privacy previews, and recovery audits. Human annotations remain outside managed
blocks and expected content hashes protect every write after a workspace load.

The derived experiment index and rebuild journal live under
`.lifeos/experiments/`. They can be deleted and rebuilt from Markdown. Daily and
weekly review adapters produce evidence-fingerprinted contextual items. Analysis
and history views are derived. Changes to goals, plans, tasks, habits, metrics,
notes, reminders, or calendar-like structures use the shared proposal engine.

The bridge exposes typed `experiment.*` capabilities, while the Obsidian plugin
remains a thin graphical client for design, tracking, analysis, evidence, history,
proposals, migration, recovery, and visualization models. Local creation, tracking, analysis, and review
integration require no model. Optional assistance uses provider-neutral contracts
and bounded, inspectable source selection. See
[Personal Experiment Architecture](personal-experiment-architecture.md) and
[Personal Experiments](user-manual/12-personal-experiments.md).

## Rich capture

Rich captures are canonical Markdown under `captures/YYYY/`, with canonical
attachment manifests under `attachments/manifests/` and original bytes under
content-addressed `attachments/originals/` paths. Python owns lifecycle,
optimistic writes, hashes, deduplication, extraction, inference decisions,
privacy previews, linking, merge and split, retrieval representations, review
adapters, experiment mappings, proposals, migration, recovery, and visualization
models. The Obsidian plugin is a thin UI client over additive `capture.*` bridge
capabilities.

Runtime state under `.lifeos/captures/` is disposable. It includes extraction
results, processing jobs, indexes, checkpoints, previews, embeddings, galleries,
timelines, and charts. Deleting it cannot delete canonical Markdown or original
files. See [Rich Capture Architecture](rich-capture-architecture.md),
[Rich Capture Protocol](rich-capture-protocol.md), and
[Rich Capture User Manual](user-manual/13-rich-capture.md).

## Cross-device vault coherence

LifeOS supports one human using one canonical Markdown vault view across several devices, but
its initial distributed-systems contract deliberately has **one active LifeOS mutation
authority at a time**. Obsidian Sync, Syncthing, Google Drive, a mounted filesystem, Git-based
transport, or another provider may replicate canonical files; the sync transport is outside
LifeOS core and does not become a second writer protocol.

Human Obsidian edits remain ordinary filesystem edits. A later `lifeos scan`, MCP ingestion
preflight, retrieval synchronization, or other deterministic refresh reconciles disposable
state from the filesystem. `.lifeos/` registries, retrieval indexes, embeddings, caches, and
runtime activity are node-local rebuildable state and should not be treated as authoritative
sync payload. The active LifeOS node owns proposal/application Git activity for that canonical
view; synchronized clients do not need to commit independently.

For canonical artifacts that carry a durable frontmatter `id`, LifeOS treats three facts
separately:

```text
stable note id  -> which canonical note is this?
current path    -> where is that note in this vault view now?
content hash    -> which exact reviewed version is this?
```

The registry and retrieval index rebuild this mapping from Markdown. A unique stable ID can
therefore preserve note identity across a pure rename/move, while duplicate IDs fail closed.
Legacy notes without a stable ID remain path-addressable but cannot be automatically followed
through relocation. Durable wiki notes are expected to acquire stable IDs; the broader
selective-ID policy remains defined by DD-006.

Existing-note ingestion proposals bind stable target ID, reviewed path, and reviewed base hash
into proposal metadata before publication. Because metadata extensions participate in the
review digest, this identity evidence is itself reviewed. Application never uses the ID to
weaken the patch's base-hash guard. If an identified target moves, pending or approved proposals
are not silently retargeted. They are stale until a fresh draft/review establishes the new path
and re-runs path-scoped instruction, privacy, ownership, authorization, and target-type checks.
The same ID with changed content is stale; a missing, changed, or ambiguous ID is blocked.

Offline mobile capture needs no LifeOS process: the phone may create normal Markdown, sync it
later, and the active node discovers it on reconciliation. Conflict copies, partial sync views,
and delayed edits are treated as observable filesystem state, not provider-specific signals.
When LifeOS cannot prove identity and version from the current canonical view it stops rather
than guessing. See [Cross-Device Vault Coherence](cross-device-vault-coherence.md) and the
[user workflow chapter](user-manual/16-cross-device-vault-coherence.md).

## MCP deployment and always-on home node

Deployment transport is an adapter around the same Python MCP/facade/business-rule core,
not a second LifeOS API implementation. Network transport narrows capabilities rather than
forking semantics:

```text
local MCP client                  remote MCP client
       |                                 |
     STDIO                    authenticated Streamable HTTP
       |                                 |
       +---------- shared MCP runtime ---+
                         |
                deterministic LifeOS core
                         |
        canonical vault + Git + disposable runtime
```

`lifeos-mcp` remains the first-class local STDIO entry point. `lifeos serve` is the explicit
long-lived service entry point. The network mode uses stateless Streamable HTTP so MCP session
memory is not canonical state; each authenticated HTTP request re-establishes the configured
actor context before invoking the shared tool/facade core. The home-node tool surface omits
`proposal_approve` and `proposal_apply` before dispatch; local STDIO retains the full lifecycle
surface.

The service has three HTTP boundaries:

- `/mcp` requires a bearer token and then passes through MCP transport Host/origin protection;
- `/healthz` is a public, content-free liveness probe;
- `/readyz` requires the bearer token and reports policy-neutral service storage readiness.

`/readyz` does not traverse protected Markdown and protected note identity/content cannot change
its 200/503 result. Detailed doctor, retrieval-policy, coherence, ownership, provenance, hash,
stale-write, and recovery checks remain at their operation-specific boundaries. The service
requires a writable canonical vault, a real non-symlink `proposals/` directory, and usable
runtime storage. Proposal artifact publication revalidates the proposal root and performs
creation/writes relative to no-follow directory descriptors, so a path swap cannot redirect a
draft into human-owned content or outside the vault.

The bearer secret is deployment state, never canonical Markdown or normal activity output. It
is supplied through `LIFEOS_SERVICE_TOKEN` or an environment-selected secret file, with exactly
one source configured. The service process has one explicit stable `--actor-id`; authenticated
request activity records that actor in disposable runtime metadata without recording the bearer
secret. An authenticated remote client may explore, create guarded drafts, and explicitly submit
a proposal. Approval and application remain trusted human/local capabilities, and forbidden
network lifecycle tools cannot inspect proposal status or review digest because they are absent
from the transport capability set.

Network defaults fail closed. Direct service startup binds to loopback. Non-loopback binding
requires an explicit Host allowlist, and the deployment guide requires a private LAN/VPN overlay
or TLS-terminating authenticated reverse proxy rather than unauthenticated public Internet
exposure. LifeOS does not own DNS, certificates, routers, VPN configuration, or a general sync
transport.

The generic OCI image is the supported deployment unit for Linux/NAS/Raspberry Pi-class nodes.
The container keeps the canonical vault/Git view on a persistent writable mount while
`.lifeos/` runtime state may live on a separate disposable/rebuildable volume. Full validation
deletes runtime state, invokes an authenticated MCP `registry_refresh`, verifies registry state
is actually recreated, exercises restart behavior, and builds the same image for `linux/arm64`.
A Home Assistant Yellow running Home Assistant OS uses a thin Supervisor App wrapper around this
multi-architecture image; Home Assistant-specific packaging does not enter LifeOS core.

This service topology does not change DD-089: there is still one active LifeOS mutation
authority for a canonical synchronized view. A remote client is a transport consumer of that
authority, not an independent writer. See DD-091 and
[Setup & Installation](user-manual/04-setup-and-installation.md#415-run-an-always-on-home-node).

## Recovery-readiness diagnostics

`lifeos doctor` exposes recovery evidence as a deterministic, read-only layer. It does not
commit, push, restore, scan, repair, or create a backup. Recovery diagnostics operate on path,
filesystem, and Git metadata and do not need canonical note bodies to determine coverage.

Recovery has three independent evidence classes:

- **Canonical Git coverage** reports whether the configured vault is inside a Git repository,
  whether committed canonical history exists, the latest commit that actually affected the
  configured vault, and current staged, modified, deleted, untracked, or ignored canonical
  paths. Git queries are path-scoped so unrelated changes in a parent repository do not become
  LifeOS recovery evidence. Staging remains uncommitted state. Commit age is informational and
  is not itself a failure when current canonical state is fully represented by history.
- **External backup/snapshot evidence** remains provider-neutral. Local commits, configured Git
  remotes, and remote-tracking refs do not prove an independent current copy. When LifeOS lacks
  deterministic evidence, `recovery.backup.external` is `unknown` rather than `pass`; the doctor
  does not manufacture certainty about third-party backup state.
- **Disposable runtime** explicitly records that `.lifeos/` registry, activity, index,
  graph/export, cache, processing, and similar derived state is rebuildable. Runtime paths are
  excluded from canonical Git-gap warnings and are never recommended for committing as a
  recovery fix.

The JSON recovery section carries stable diagnostic IDs, status, severity, summary, optional
remediation, and only the relative exposed paths needed to fix a local gap. The initial IDs are
`recovery.git.repository`, `recovery.git.last_canonical_commit`,
`recovery.git.canonical_objects`, `recovery.git.uncommitted_canonical`,
`recovery.git.untracked_canonical`, `recovery.git.ignored_canonical`,
`recovery.backup.external`, and `recovery.runtime.disposable`. Operational doctor readiness
remains separate from this recovery evidence so advisory recovery gaps do not silently redefine
whether the local LifeOS application can run.
