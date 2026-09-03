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

LIFEOS-1701 owns the parser and exact serialization, but the Phase 17 semantic contract is fixed here so later tasks do not invent product behavior.

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

`source_id`, `observation_id`, `event_id`, `origin.source_ref`, review timestamps, and `evaluation` are optional when the source or pattern does not have that concept. Required-field details and typed validation belong to LIFEOS-1701, but implementations must preserve the semantics above.

Machine-managed evidence summaries, evidence-health diagnostics, and other refreshable renderings use validated managed blocks. Human reflection, qualifications, competing explanations, and user-created prose remain outside managed blocks and are preserved byte-for-byte by refresh workflows.

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

Historical reviewed hashes never silently advance. A current source may therefore be:

- `unchanged`: reviewed identity/path resolves and the reviewed hash still matches;
- `moved`: the same unique stable source ID resolves to another path while the reviewed content version is still identifiable;
- `changed`: the source resolves but current bytes no longer match the reviewed hash;
- `missing`: the reviewed source cannot be resolved;
- `ambiguous`: stable identity resolves to more than one canonical source;
- `deleted`: deletion is known from available canonical/registry evidence rather than merely inferred from silence.

A moved source may be explained as a relocation, but the canonical reviewed reference is not silently rewritten. Changed, missing, moved, deleted, or ambiguous evidence becomes explicit review evidence. Missing evidence is **unknown**, not counter-evidence. A changed source is not automatically interpreted as support or contradiction.

## Counter-evidence and competing explanations

Supporting evidence does not erase contesting evidence. Contesting evidence does not automatically falsify the pattern. Contextual evidence can explain conditions or confounders without being counted as support.

When an agent assists with a semantic proposal, the review payload must keep the concise hypothesis, rationale, supporting evidence, contesting evidence, competing explanations, limitations, and proposed confidence class inspectable. Hidden chain-of-thought is neither required nor stored.

A later revision may change the statement or confidence only through a fresh proposal bound to the evidence actually reviewed. Historical proposal snapshots and the pattern's prior Git history preserve what was accepted earlier.

## Re-evaluation and review triggers

Re-evaluation answers **does this deserve review?**, not **is this belief true?**

For patterns that opt into a supported deterministic evaluation recipe, LifeOS may rerun factual analysis against current canonical observations. The initial supported family is deliberately narrow and reuses the cautious Phase 7 forms:

- numeric metric association;
- activity-versus-outcome comparison.

The recalculation may detect materially new evidence, changed evidence versions, weaker evidence, direction reversal, new contesting evidence, stale evidence, missing or ambiguous evidence, or a due review date. Those facts become review reasons and a review recommendation. They never directly rewrite `statement`, `status`, `confidence`, or reviewed evidence.

For semantic or manually authored patterns without a deterministic recipe, automation is limited to factual evidence-state checks and review timing. LifeOS does not run an autonomous vault-wide psychological contradiction search merely because a pattern exists.

No new observations is not evidence against a pattern. A weaker estimate is not automatically a contradiction. Direction reversal is a reason to inspect the evidence, not a deterministic declaration that the user's prior interpretation was false.

## Reviews and attention

Personal-pattern maintenance reuses first-class review semantics rather than creating a separate obligation queue.

Weekly review may surface a bounded optional set of:

- new seeds that the user chose to track;
- materially changed active patterns;
- due patterns;
- `needs-review` patterns;
- unresolved contesting evidence.

Daily review may surface only an urgent or explicitly pinned pattern-review item. A pattern is never inserted into every daily or weekly review merely because it is `active`.

Review decisions remain evidence-fingerprint scoped under DD-058. A dismissal suppresses the unchanged prompt; changed evidence creates a new context that may surface again. Completing a review never implies agreement with the pattern and never mutates the pattern directly. Proposed changes use the normal proposal engine.

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
- **Today:** pattern review attention may be surfaced when urgent or explicitly pinned. Direct pattern-driven planner scoring, ranking, selection, duration, energy, or motivation changes are deferred beyond Phase 17.
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

## Obsidian boundary

The Phase 17 Obsidian workspace is a thin client over Python read models and proposal builders. It will expose Active, Needs review, Seeds, and Archived views; evidence health; supporting and contesting sources; evidence changes; and proposal-backed Track, Adopt, Revise, Contest, and Archive actions.

Refresh is read-only. TypeScript does not parse canonical pattern semantics into a parallel business-rule implementation and does not write pattern Markdown directly. Missing or corrupt derived state degrades to an explicit rebuild/recovery state rather than to canonical data loss.

## Graph boundary

The existing optional `personal-patterns` Graphify view remains derived and non-authoritative. It may help find relationships or navigation paths, but an inferred graph edge does not promote a pattern, change confidence, or become canonical evidence without a normal reviewed proposal.

## Recovery and migration

The Phase 17 recovery contract is conservative:

- delete/rebuild of `.lifeos/` loses no canonical pattern knowledge;
- proposal interruption uses the existing recovery transaction model;
- arbitrary existing Markdown under `patterns/` remains untouched;
- migration is offered only when a recognizable legacy contract can be identified deterministically;
- migration preview never invents semantic status, confidence, evidence role, or reviewed meaning;
- unsupported future pattern schemas fail with typed diagnostics rather than being guessed.

## Phase 17 implementation sequence

The task chain is intentionally ordered:

1. **LIFEOS-1700** defines these architecture and product semantics.
2. **LIFEOS-1701** implements the canonical pattern artifact contract.
3. **LIFEOS-1702** implements evidence lineage, source-state resolution, and fingerprints.
4. **LIFEOS-1703** adds proposal-gated pattern lifecycle workflows.
5. **LIFEOS-1704** adds deterministic re-evaluation and review triggers.
6. **LIFEOS-1705** builds the rebuildable Personal Model read model.
7. **LIFEOS-1706** integrates bounded pattern maintenance with daily and weekly reviews.
8. **LIFEOS-1707** adds bounded pattern evidence to context and reflection surfaces.
9. **LIFEOS-1708** builds the Obsidian Personal Model workspace.
10. **LIFEOS-1709** adds evidence-bounded agent-assisted pattern proposals.
11. **LIFEOS-1710** validates recovery, migration, release, end-to-end behavior, and complete user documentation.

This sequence preserves one central rule: **evidence may create a reason to review, but only trusted human review can turn a semantic interpretation into durable accepted working context.**
