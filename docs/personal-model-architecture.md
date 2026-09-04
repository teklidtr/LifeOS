# Evidence-Backed Personal Model Architecture

## Purpose

The Personal Model is LifeOS's evidence-backed way to remember reviewable hypotheses about how the user tends to work, learn, recover, choose, or respond to context. It is deliberately not a biography, personality profile, diagnosis, productivity score, or second canonical database.

A personal pattern is always a **working hypothesis**. `status: active` means the user has reviewed the hypothesis and currently finds it useful enough to keep in active context. It does not mean the statement has become objective truth, a causal conclusion, or an instruction.

This architecture extends the cautious Phase 7 observation layer. Existing `lifeos observe patterns` output remains ephemeral analysis whose `candidate` label is not a canonical lifecycle state. A candidate may later ground a proposal to track a pattern as `seed`, but deterministic observation never promotes itself into `patterns/`.

## Authority and state boundaries

LifeOS keeps four concerns separate:

```text
canonical evidence                    canonical interpretation
journal / experiments / reviews  ->  patterns/*.md
captures / goals / plans / ...        one reviewed hypothesis per artifact
          |                                      |
          +------------------+-------------------+
                             |
                             v
                    derived Personal Model
                    .lifeos/personal-model/
                             |
                 +-----------+-----------+
                 |                       |
                 v                       v
          bounded reflection       review attention
          and agent context        and Obsidian views
```

### Canonical patterns

Recognized personal-pattern artifacts live under `patterns/` as ordinary human-readable Markdown. Phase 17 introduces `pattern_schema: 1` and `type: pattern`; Markdown under `patterns/` without a recognized pattern schema remains ordinary user content and is not silently converted, indexed as a healthy pattern, or rewritten.

A canonical pattern owns the durable semantic statement, lifecycle status, confidence class, evidence references, evidence fingerprint, review timing, origin, and human reflection. The pattern file is human-owned. It is never registered as generated-owned merely because an agent proposed its contents.

### Derived Personal Model

The aggregate Personal Model is a deterministic read model under `.lifeos/personal-model/`. It may index canonical patterns by stable ID, status, confidence, evidence health, review reasons, freshness, origin, and review-due state. It contains no independent semantic authority.

Deleting `.lifeos/personal-model/`, the registry, retrieval state, graph state, or other disposable runtime data must not remove or weaken canonical personal knowledge. Rebuilding the Personal Model means rereading recognized `patterns/*.md` artifacts and recomputing factual diagnostics.

There is no canonical generated `profile/personal-model.md`, no automatically maintained personality narrative, and no aggregate productivity, wellness, personality, readiness, or life score.

## Canonical pattern contract

LIFEOS-1701 implements this boundary in `lifeos.patterns`. Recognition is schema-led: a Markdown file under `patterns/` is a canonical pattern only when its top-level frontmatter declares `pattern_schema`. Schema version 1 then requires `type: pattern`; unsupported versions and malformed declared patterns fail with typed diagnostics. Markdown without a recognized schema remains ordinary user content.

A recognized pattern uses the common LifeOS lifecycle:

```yaml
pattern_schema: 1
type: pattern
id: pattern-example
title: Short human-readable title
description: Concise index and preview text
status: seed | active | needs-review | archived
confidence: low | medium | high
review_reasons: []
statement: A concise falsifiable-or-reviewable working hypothesis.
origin:
  kind: manual | observation | review | conversation | experiment | goal | plan | agent
  source_ref: optional canonical source reference
created_at: YYYY-MM-DDTHH:MM:SSZ
updated_at: YYYY-MM-DDTHH:MM:SSZ
last_reviewed_at: YYYY-MM-DDTHH:MM:SSZ
review_due_at: YYYY-MM-DDTHH:MM:SSZ
evidence_fingerprint: sha256:<digest>
evidence:
  - path: journal/2026-08-20.md
    source_id: optional-stable-source-id
    content_hash: sha256:<digest>
    role: supporting | contesting | contextual
    observation_id: optional-stable-observation-id
    event_id: optional-stable-event-id
evaluation:
  kind: optional deterministic recipe kind
  parameters: {}
```

`pattern_schema`, `type`, `id`, `title`, `description`, `status`, `confidence`, `review_reasons`, `statement`, `origin`, `created_at`, `updated_at`, `evidence_fingerprint`, and `evidence` are required in schema 1. `source_id`, `observation_id`, `event_id`, `origin.source_ref`, review timestamps, and `evaluation` are optional when the source or pattern does not have that concept.

Stable pattern IDs use lowercase letters, digits, dot, underscore, or hyphen. Evidence paths are canonical vault-relative paths and reject traversal, absolute paths, Windows-drive forms, backslashes, and other unsafe path forms through the shared vault validator. Evidence content hashes and the stored fingerprint are exact lowercase `sha256:` digests. Timestamps are timezone-aware ISO 8601 values. Optional evaluation parameters are limited to portable scalar, list, and string-keyed mapping values and serialize with deterministic key ordering.

The serializer emits one `personal-pattern-evidence` managed block containing a refreshable evidence summary. The parser requires that managed boundary exactly once for a recognized schema-1 pattern. Human reflection, qualifications, competing explanations, headings, whitespace, and other user-created prose before or after that managed block are separate ownership regions and can be round-tripped byte-for-byte. The managed summary is derived presentation, not evidence authority.

LIFEOS-1701 validates the stored `evidence_fingerprint` shape but deliberately does not calculate or advance it. LIFEOS-1702 owns evidence normalization, source-state resolution, and fingerprint computation so artifact parsing cannot silently rewrite reviewed evidence versions.

## Lifecycle semantics

The four lifecycle states answer **what should LifeOS do with this hypothesis now?** They do not answer whether it is true.

- `seed`: Track this hypothesis. Evidence may be sparse or the interpretation may still be exploratory. A seed is not accepted as a useful default belief.
- `active`: The user has explicitly reviewed the evidence and accepts the hypothesis as useful working context for now. It remains provisional and contestable.
- `needs-review`: Material evidence state, review timing, or an explicit user decision says the hypothesis deserves another look. It does not mean disproved.
- `archived`: Keep the history and evidence lineage, but exclude the hypothesis from ordinary active context and routine review selection unless history is explicitly requested.

`confidence` is independent of lifecycle. `low | medium | high` is a qualitative evidence posture, not a model probability and not a user score. A high-confidence pattern can become `needs-review`; a low-confidence seed can remain a seed; archiving says nothing about confidence.

The Phase 7 observation value `candidate` stays outside this lifecycle. An observation candidate can be input evidence for a proposal, never an implicit fifth pattern status.

## Proposal and ownership boundary

Every consequential semantic transition is proposal-gated:

```text
candidate or human idea
        |
        v
reviewable draft proposal
        |
        +--> reject / leave unchanged
        |
        v
explicit trusted review
        |
        v
create or patch human-owned patterns/*.md
```

Creating a canonical seed means **track this hypothesis**, not **accept this as true**. Promoting a seed to `active`, revising its statement or reviewed evidence, moving it to `needs-review`, resolving that review, changing confidence, or archiving it all use the shared proposal lifecycle.

New pattern files use the existing human-file creation boundary. Changes to existing patterns use base-hash-bound `patch_human_file` behavior. Existing proposal review snapshots, trusted authorization, stale-target checks, application-time validation, recovery transactions, and interruption semantics remain authoritative.

An agent may propose a pattern but cannot select the approving identity, approve its own interpretation, or directly mutate `patterns/`. MCP and authenticated home-node transport do not weaken that rule.

LIFEOS-1703 implements this boundary with typed `lifeos.patterns` proposal requests for Track, Adopt, Revise, Needs review, Resolve review, and Archive. The builder stops at a draft proposal, records the transition reason and reviewed evidence fingerprint in proposal metadata, uses `create_file` only for an absent new seed, and uses a current-content-hash-bound `patch_human_file` for every existing pattern. Resolving `needs-review` requires an explicit `seed` or `active` destination, so completing a review cannot silently become adoption. Submission, approval, rejection, stale-target checks, application, and interrupted-write recovery remain the shared proposal engine's responsibility.

The proposal engine's generic rule still rejects `patch_human_file` for Markdown containing LifeOS-managed blocks. Canonical patterns are the narrow schema-owned exception because the required `personal-pattern-evidence` block is derived presentation inside an otherwise human-owned pattern file. Preflight and application permit that exception only when the original and candidate are both recognized canonical patterns, the stable pattern ID is unchanged, and serializing the candidate metadata plus its human-owned body regions reproduces the candidate bytes exactly. Ordinary managed Markdown, malformed pattern candidates, identity changes, and managed-summary text that disagrees with canonical pattern metadata remain rejected.

## Evidence references and lineage

A durable personal interpretation must remain traceable to the exact evidence versions reviewed when the interpretation was created or changed.

Each evidence reference keeps separate facts for:

- stable source identity when the source has one;
- reviewed vault-relative path;
- reviewed SHA-256 content version;
- evidence role: `supporting`, `contesting`, or `contextual`;
- optional stable observation or event identity inside the source.

This follows DD-090: identity, location, and version are different facts. A path is not promoted into stable identity, and a stable ID does not authorize silently following changed content.

The evidence fingerprint is deterministic and ordering-independent. LIFEOS-1702 normalizes each reference to the tuple of role, stable source ID when present, reviewed path, reviewed content hash, observation ID when present, and event ID when present; references are sorted by that normalized tuple, encoded with the repository's canonical JSON rules, and SHA-256 hashed with the `sha256:` prefix. Exact duplicate normalized references do not create multiple fingerprint contributions.

`lifeos.patterns.normalize_evidence_reference()` exposes that normalized tuple without mutating the canonical reference, while `compute_evidence_fingerprint()` performs the deterministic deduplication, ordering, canonical JSON encoding, and hashing. Evidence role is part of the tuple, so the same reviewed source cannot collapse supporting and contesting evidence into one fingerprint contribution.

Historical reviewed hashes never silently advance. A current source may therefore be:

- `unchanged`: reviewed identity/path resolves and the reviewed hash still matches;
- `moved`: the same unique stable source ID resolves to another path while the reviewed content version is still identifiable;
- `changed`: the source resolves but current bytes no longer match the reviewed hash;
- `missing`: the reviewed source cannot be resolved;
- `ambiguous`: stable identity resolves to more than one canonical source;
- `deleted`: deletion is known from available canonical/registry evidence rather than merely inferred from silence.

`lifeos.patterns.resolve_evidence_states()` resolves those facts against the caller's current registry snapshot and requires a caller-supplied authorized path predicate. Registry rows outside that predicate do not participate in identity ambiguity and cannot expose current path/hash facts. Within the authorized scope, `source_id` is the identity lookup key; more than one active match is `ambiguous`, a unique same-hash match at a new path is `moved`, and a unique different-hash match is `changed`. Without `source_id`, resolution is path-bound and does not invent rename continuity. A visible registry deletion observation yields `deleted`; complete visible absence yields `missing`. Diagnostics retain the immutable reviewed reference and report current path/hash separately. Internal registry tombstone paths are never surfaced as canonical evidence locations.

A moved source may be explained as a relocation, but the canonical reviewed reference is not silently rewritten. Changed, missing, moved, deleted, or ambiguous evidence becomes explicit review evidence. Missing evidence is **unknown**, not counter-evidence. A changed source is not automatically interpreted as support or contradiction.

## Counter-evidence and competing explanations

Supporting evidence does not erase contesting evidence. Contesting evidence does not automatically falsify the pattern. Contextual evidence can explain conditions or confounders without being counted as support.

When an agent assists with a semantic proposal, the review payload must keep the concise hypothesis, rationale, supporting evidence, contesting evidence, competing explanations, limitations, and proposed confidence class inspectable. Hidden chain-of-thought is neither required nor stored.

A later revision may change the statement or confidence only through a fresh proposal bound to the evidence actually reviewed. Historical proposal snapshots and the pattern's prior Git history preserve what was accepted earlier.

## Re-evaluation and review triggers

Re-evaluation answers **does this deserve review?**, not **is this belief true?**

LIFEOS-1704 implements the read-only assessment boundary in `lifeos.patterns`. A pattern can opt into one of two initial deterministic recipe kinds:

- `numeric-metric-association` with `outcome`, `factor`, optional `min_samples`, and optional `stale_after_days` parameters;
- `activity-outcome-comparison` with `outcome`, `activity`, optional `min_samples`, and optional `stale_after_days` parameters.

The recipes call the existing cautious Phase 7 numeric-association and activity-comparison analyzers rather than introducing another statistics implementation. When `min_samples` is omitted, each recipe inherits the corresponding analyzer default: 5 paired observations for numeric association and 3 observations per activity group. `stale_after_days` is opt-in; when present it must be a positive integer and creates a staleness review reason once the newest usable dated observation reaches that age. Unknown recipe kinds or recipe-specific parameters fail closed instead of being silently ignored.

The last reviewed evidence fingerprint remains immutable review context. Re-evaluation first checks whether the currently declared evidence references still reproduce that fingerprint and separately resolves each reviewed source as unchanged, moved, changed, missing, deleted, or ambiguous. A changed fingerprint, changed source version, move, deletion, missing source, or ambiguity is an inspectable review reason; none of those facts is automatically interpreted as contradiction.

For deterministic baseline comparison, LifeOS reconstructs the reviewed analysis only from journal evidence whose exact reviewed bytes are still identifiable as `unchanged` or same-hash `moved`. If a reviewed journal source changed, disappeared, was deleted, or became ambiguous, LifeOS does not invent historical bytes or compare a guessed baseline. It still runs the current recipe against authorized current observations and reports the factual evidence-state reason.

New usable dated observations after `last_reviewed_at` that were not part of the reconstructable reviewed evidence are reported as materially new evidence. When the reconstructable reviewed result surfaced a candidate, a current result that disappears or drops to a lower Phase 7 evidence-strength class becomes `weaker-evidence`. An aggregate direction reversal becomes both a `direction-reversal` reason and deterministic counter-evidence to the previously reviewed direction. The wording remains deliberately narrow: reversal is a reason to inspect the evidence, not a declaration that the hypothesis is false.

A due `review_due_at` timestamp is an independent review reason. Manual or semantic patterns without an evaluation recipe receive only factual evidence-state, fingerprint, and timing checks; LifeOS does not run an autonomous vault-wide psychological contradiction search. No new observations is not evidence against a pattern, and silence never becomes negative evidence under DD-041.

`assess_pattern_review()` and `PatternReviewService.assess()` are read-only. They return the exact pattern version assessed, both fingerprint values, the deterministic reports when available, and explicit reason codes/messages. They do not rewrite `statement`, `status`, `confidence`, evidence references, or any Markdown. Archived patterns may still have diagnostics but are excluded from routine review recommendations.

A review recommendation also does not create a proposal by itself. `PatternReviewService.create_review_proposal()` is a separate explicit action that turns a still-current assessment into the existing `mark-needs-review` draft proposal. It rejects a stale assessment if the canonical pattern changed after assessment, and the normal proposal workflow still governs submission, approval, rejection, application, authorization, and recovery. The re-evaluator never approves or applies its own recommendation.

## Reviews and attention

Personal-pattern maintenance reuses first-class review semantics rather than creating a separate obligation queue.

Weekly review may surface a bounded optional set of:

- new seeds that the user chose to track;
- materially changed active patterns;
- due patterns;
- `needs-review` patterns;
- unresolved contesting evidence.

LIFEOS-1706 makes that bound concrete at eight items per weekly snapshot. Selection is deterministic: `needs-review` items sort before due items, contesting-evidence changes, other material evidence changes, and new seeds; stable pattern ID breaks ties. A quiet `active` pattern is not selected simply because it is active.

Daily review is fail-closed for personal patterns. It may surface at most three pattern items and only when the caller or workspace explicitly passes stable IDs as urgent or pinned, with urgent items first. In the absence of those IDs the daily pattern section is empty, even when a pattern is due or already `needs-review`. Urgency and pinning are not inferred from free-form `review_reasons`, and Phase 17 does not add a second canonical pin field merely to make daily review noisy.

Each selected item reuses the canonical review item identity `personal-pattern:<pattern-id>`. Its review fingerprint is derived from review-relevant context rather than the whole pattern note: lifecycle status, confidence, reviewed evidence fingerprint, evidence health, review timing, review reasons, deterministic trigger reasons, and current evidence diagnostics. Arbitrary edits to human-owned reflection prose therefore do not by themselves create a new review context. Source presentation stays bounded to the canonical pattern plus up to three evidence references.

Review decisions remain evidence-fingerprint scoped under DD-058. A `dismiss_for_review` decision suppresses the same fingerprint in later continuity; changed evidence or another review-relevant state change creates a new fingerprint that may surface again. Acknowledge, defer, dismiss, and open-source behavior uses the ordinary review decision machinery rather than a pattern-specific state machine.

Completing a review never implies agreement with the pattern and never mutates the pattern directly. `propose_change` is an explicit handoff that validates the still-visible review fingerprint and still-current pattern context before creating the existing `mark-needs-review` draft. The normal submit, approve, and apply lifecycle remains required after that draft exists.

Pattern review resolution uses the disposable registry only to resolve current source identity and content-hash facts before building the Personal Model item. Refreshing those derived facts does not advance reviewed hashes or make SQLite authoritative; canonical pattern Markdown and canonical review artifacts remain the durable sources of truth.

## Context, retrieval, and reflection

Patterns are evidence sources, not runtime instructions.

Relevant canonical pattern notes may contribute bounded context to:

- Context Packs and iterative retrieval;
- knowledge conversations;
- goal-to-plan clarification and replanning explanation;
- personal-experiment design context;
- daily and weekly review explanation;
- Obsidian Personal Model inspection.

Every inclusion keeps the pattern's stable ID, lifecycle status, confidence class, evidence-health state, and canonical reference visible. `needs-review` is not flattened into an active assertion. `seed` content is visibly exploratory. `archived` content is excluded by default unless history or an explicit reference requires it.

`system/instructions.yml` remains the only allowlisted source of vault-specific routed instruction authority. Text inside a pattern, including imperative-looking prose, cannot authorize a mutation, override policy, or become a hidden personality prompt.

The aggregate Personal Model is never injected wholesale into every provider request. Relevance and size are bounded for the question at hand, and local deterministic operation remains possible without a model provider.

LIFEOS-1707 makes that boundary concrete through `build_personal_pattern_context()`. The typed read contract carries the canonical pattern ID, path and content hash, lifecycle status, confidence, evidence health and fingerprint, and at most three canonical evidence references. Each item is explicitly marked `evidence-not-instruction` with `can_authorize_mutation: false`. Lifecycle meaning remains visible as `reviewed-working-hypothesis` for `active`, `exploratory-hypothesis` for `seed`, `uncertain-needs-review` for `needs-review`, and `archived-history` only when an archived pattern is explicitly referenced.

Context Packs reuse their existing source bound and relevance ranking rather than appending a second Personal Model payload. A selected pattern source receives the evidence envelope above, while ordinary archived patterns are removed before capped relevance ranking. Caller path filters and planning exclusions are enforced before Personal Model content access, and the typed title, statement, reference set, and rendered evidence envelope remain bounded. Redaction is applied inside typed pattern metadata, including the human-readable title and bounded evidence-reference paths, before serialization. Evidence-state resolution uses a disposable snapshot of the persisted node-local registry history and refreshes that snapshot inside the caller's scope; tombstones can therefore distinguish `deleted` from `missing` without mutating the runtime registry or making SQLite authoritative. Knowledge conversations reuse those bounded excerpts; goal-to-plan clarification adds only relevant pattern evidence without changing readiness or planner selection; experiment previews apply the same provider-scope, redaction, and byte-budget rules to both rendered excerpts and nested typed pattern metadata; canonical daily and weekly review items continue to expose their existing bounded pattern evidence and source explanations.

## Privacy and provider disclosure

Personal-pattern evidence uses the existing retrieval-policy boundary rather than introducing a weaker privacy path.

- Excluded paths never enter derived retrieval/provider payloads.
- Protected scopes remain default deny.
- External disclosure of protected content requires both policy permission and an explicit grant for the current request.
- Redaction occurs before provider invocation where the existing policy supports it.
- Provider previews disclose the selected bounded sources and material payload rather than sending an opaque profile.
- Provider-specific fields do not enter canonical pattern artifacts.
- Derived Personal Model state must not copy protected source bodies into a less-protected cache or response merely to make later retrieval convenient.

A canonical pattern itself follows normal path policy. Phase 17 does not classify every pattern as protected automatically, because doing so would create a second privacy taxonomy. The source evidence and requested operation determine the applicable policy.

## Goals, plans, Today, and experiments

Patterns may inform reflection without becoming automatic control policy.

- **Goals and plans:** relevant patterns may appear as bounded evidence during clarification or replanning. A pattern cannot directly create, reprioritize, or rewrite a goal, plan, or task.
- **Today:** pattern review attention may be surfaced when urgent or explicitly pinned. Direct pattern-driven planner scoring, ranking, selection, duration, energy, motivation changes are deferred beyond Phase 17.
- **Experiments:** a pattern may motivate an experiment, and experiment evidence may later support, contest, or contextualize a pattern. Experiment completion never auto-revises the pattern.
- **Conversations:** an evidence-grounded conversation may propose a new or revised pattern, but the result stops at a draft proposal.

This keeps personal interpretation from becoming a hidden planning policy. If a future phase wants pattern-driven planner behavior, it requires an explicit architecture/task decision rather than emerging as an incidental context side effect.

## Deterministic versus agent-assisted responsibilities

### Deterministic LifeOS responsibilities

LifeOS code owns:

- safe path traversal and pattern schema validation;
- stable-ID uniqueness checks;
- source hash and identity verification;
- evidence normalization and fingerprints;
- factual evidence-state diagnostics;
- supported deterministic re-evaluation recipes;
- derived Personal Model rebuild and ordering;
- review timing and bounded review selection;
- protected-scope and disclosure enforcement;
- proposal construction, snapshots, authorization, stale-write checks, application, and recovery;
- typed Python/bridge contracts and UI-ready read models.

### Agent responsibilities

An external agent may:

- interpret explicitly bounded evidence;
- propose a concise semantic hypothesis;
- identify supporting, contesting, and contextual evidence;
- propose competing explanations and limitations;
- propose a confidence class;
- explain why a pattern may deserve review.

The agent cannot establish a hypothesis as truth, infer immutable identity traits, diagnose the user, approve a proposal, bypass protected-scope policy, or directly write canonical pattern semantics.

### Agent-assisted proposal boundary

LIFEOS-1709 exposes two bounded proposal-producing operations through the shared MCP runtime: one for a new `seed` hypothesis and one for a revision of an existing canonical pattern. The external agent supplies only evidence it actually inspected, including each canonical vault-relative path, exact observed SHA-256 content hash, and supporting, contesting, or contextual role. Existing-pattern review also carries the exact canonical pattern hash the agent inspected.

LifeOS applies external retrieval policy before reading those selected sources, independently re-reads and hashes them, derives stable source identity only from the verified current note, and verifies the selected evidence again immediately before proposal persistence. Missing, changed, unsafe, excluded, or non-authorized protected evidence fails closed. A protected existing pattern is subject to the same external-disclosure rule before review. Protected access therefore requires both policy permission and explicit request intent; knowing a path or tool name is not sufficient.

The semantic payload is deliberately provider-neutral and review-only: concise hypothesis, rationale, proposed confidence, supporting and contesting references, competing explanations, and limitations. It is digest-bound inside ordinary proposal metadata/body and never becomes a provider-specific canonical field or hidden reasoning store. The proposal's canonical candidate remains the existing personal-pattern schema, and the existing proposal builder still owns create-versus-base-hash-bound-patch semantics.

Both operations stop at `draft`. They cannot choose an approving identity, promote a pattern to `active`, or apply canonical Markdown. When an existing pattern already has the proposed statement, confidence, and exact verified evidence set, the operation returns a deterministic no-change result and creates no proposal. Optional semantic providers may return no suggestion, time out, be unavailable, or produce malformed output without making ordinary local deterministic Personal Model operation unavailable.

## Obsidian boundary

The shipped Phase 17 Obsidian workspace is a thin client over Python read models and proposal builders. It exposes Active, Needs review, Seeds, and Archived views; hypothesis statement and confidence; evidence health and freshness; supporting and contesting sources; reviewed source versions and evidence changes; related review/experiment links; and proposal-backed Track, Adopt, Revise, Contest, and Archive actions.

Refresh is read-only. Rebuild explicitly recreates disposable Personal Model state. TypeScript does not parse canonical pattern semantics into a parallel business-rule implementation and does not write pattern Markdown directly. Missing or corrupt derived Personal Model state degrades to an explicit rebuild/recovery state rather than to canonical data loss. Existing-pattern actions bind to the inspected canonical content hash so an Obsidian edit after inspection produces a stale-target failure instead of rebasing a semantic decision onto unseen bytes.

## Graph boundary

The existing optional `personal-patterns` Graphify view remains derived and non-authoritative. It may help find relationships or navigation paths, but an inferred graph edge does not promote a pattern, change confidence, or become canonical evidence without a normal reviewed proposal.

## Recovery, compatibility, and migration

The shipped Phase 17 recovery contract is conservative:

- delete/rebuild of `.lifeos/` loses no canonical pattern knowledge;
- proposal interruption uses the existing recovery transaction model and preserves proposal/evidence lineage;
- arbitrary existing Markdown under `patterns/` remains untouched;
- only `pattern_schema` artifacts enter the canonical Phase 17 pattern contract;
- migration is offered only when a recognizable legacy contract can be identified deterministically;
- migration preview never invents semantic status, confidence, evidence role, or reviewed meaning;
- unsupported future pattern schemas fail with typed diagnostics rather than being guessed.

No pre-Phase-17 canonical Personal Model schema is currently recognized, so Phase 17 ships no heuristic converter for legacy-looking `patterns/` Markdown. Frontmatter that happens to contain fields such as `type`, `status`, or `confidence` without the recognized `pattern_schema` declaration stays user-authored ordinary Markdown. A future migration requires a separately accepted deterministic legacy contract and preview before it may rewrite anything.

## Shipped Phase 17 sequence and release contract

Phase 17 shipped through the ordered task chain:

1. **LIFEOS-1700** defined the architecture and product semantics.
2. **LIFEOS-1701** implemented the canonical pattern artifact contract.
3. **LIFEOS-1702** implemented evidence lineage, source-state resolution, and fingerprints.
4. **LIFEOS-1703** added proposal-gated pattern lifecycle workflows.
5. **LIFEOS-1704** added deterministic re-evaluation and review triggers.
6. **LIFEOS-1705** built the rebuildable Personal Model read model.
7. **LIFEOS-1706** integrated bounded pattern maintenance with daily and weekly reviews.
8. **LIFEOS-1707** added bounded pattern evidence to context and reflection surfaces.
9. **LIFEOS-1708** built the Obsidian Personal Model workspace.
10. **LIFEOS-1709** added evidence-bounded agent-assisted pattern proposals.
11. **LIFEOS-1710** closes the phase with release fixtures and documentation covering representative lifecycle/evidence histories, arbitrary `patterns/` preservation, derived-state rebuild, proposal interruption recovery, bounded large-vault behavior, local STDIO and authenticated home-node capability boundaries, and the evidence-to-Obsidian end-to-end lifecycle.

The complete user-facing workflow is documented in `docs/user-manual/19-personal-model.md`. Focused Obsidian controls remain in `docs/user-manual/personal-model.md`, and deterministic re-evaluation semantics remain in `docs/user-manual/personal-pattern-review-triggers.md`.

The central shipped rule remains: **evidence may create a reason to review, but only trusted human review can turn a semantic interpretation into durable accepted working context.**
