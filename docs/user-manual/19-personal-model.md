[← Previous: Evidence-Grounded Research](18-evidence-grounded-research.md) · [Manual home](README.md)

# 19. Evidence-Backed Personal Model

The Personal Model is LifeOS's way to keep useful interpretations about your own experience without turning them into permanent facts about you. A personal pattern is always a **working hypothesis**. It is not a diagnosis, personality type, productivity score, causal conclusion, or instruction to an agent.

Canonical hypotheses are ordinary human-readable Markdown under `patterns/`. The aggregate Personal Model under `.lifeos/personal-model/` is disposable derived state. If the derived state disappears, LifeOS rebuilds it from canonical patterns and authorized evidence.

## The complete workflow

A normal Personal Model loop is:

```text
canonical evidence
  ↓
observation or agent-assisted interpretation
  ↓
draft proposal
  ↓
human review and explicit approval
  ↓
canonical patterns/*.md working hypothesis
  ↓
deterministic evidence-state checks and optional re-evaluation
  ↓
review attention when something materially changes
  ↓
bounded context, reflection, and Obsidian inspection
  ↓
revise, keep, contest, resolve, or archive through another proposal
```

Nothing in this loop silently converts an interpretation into user truth.

## 1. Start from evidence, not a profile

Evidence can come from canonical journal entries, experiments, reviews, conversations, goals, plans, or other authorized vault sources. A durable pattern records the exact evidence references reviewed at the time, including the vault path, reviewed SHA-256 content hash, role, and stable source identity when one exists.

Evidence roles stay distinct:

- `supporting` means the source supported the reviewed interpretation;
- `contesting` means the source challenged or complicated it;
- `contextual` means the source may explain conditions or confounders without counting as support.

Missing evidence is unknown, not counter-evidence. Changed evidence is a reason to inspect the hypothesis, not proof that it became false.

## 2. Track a seed through a proposal

A new interpretation first becomes a `seed`. A seed means “this may be worth tracking,” not “LifeOS learned this about me.”

You can start in the Obsidian **Personal Model** workspace, or an MCP-connected agent can prepare an evidence-bounded draft with `personal_pattern_propose`. In both cases LifeOS creates or previews a normal proposal. The canonical `patterns/*.md` file does not exist until the proposal goes through the ordinary trusted review and application boundary.

Agent assistance receives no extra authority. The agent supplies only evidence it actually inspected, including exact content hashes. LifeOS rereads and verifies those sources before publishing a draft. A provider timeout, invalid output, changed source, unavailable protected source, or a zero-proposal result leaves canonical state unchanged.

## 3. Understand lifecycle and confidence separately

Canonical patterns use four lifecycle states:

- `seed`: exploratory and tracked, but not accepted as ordinary working context;
- `active`: explicitly reviewed and currently useful as a working hypothesis;
- `needs-review`: something about evidence, timing, or an explicit decision deserves another look;
- `archived`: preserved as history but excluded from ordinary active context and routine review selection.

Confidence is a separate qualitative evidence posture: `low`, `medium`, or `high`. It is not a model probability or a score. An active pattern can have low confidence; a high-confidence pattern can need review; archiving does not say whether a hypothesis was right or wrong.

## 4. Adopt, revise, contest, resolve, or archive explicitly

Every consequential semantic transition remains proposal-gated:

- **Adopt** moves a reviewed seed or resolved hypothesis into `active` working context.
- **Revise** changes the statement, confidence, or reviewed evidence after inspection.
- **Contest** moves a hypothesis to `needs-review` without declaring it false.
- **Resolve review** requires an explicit destination of `seed` or `active`.
- **Archive** keeps lineage while removing the hypothesis from ordinary active use.

Pattern changes bind to the exact canonical content hash that was inspected. If the note changes before application, the proposal becomes stale instead of silently rebasing onto newer human text. Interrupted application uses the shared proposal recovery transaction, preserving proposal state and evidence lineage.

## 5. Re-evaluation asks whether review is needed

LifeOS does not run an autonomous psychological profiler over the vault. Re-evaluation is deliberately narrower: **does this working hypothesis deserve another look?**

For patterns with supported deterministic evaluation recipes, LifeOS can compare the reviewed evidence state with authorized current observations. It can surface factual reasons such as:

- materially new evidence;
- weaker evidence than the reviewed baseline;
- an aggregate direction reversal;
- new contesting evidence;
- a changed, moved, missing, deleted, or ambiguous source;
- a changed evidence fingerprint;
- a configured review date becoming due;
- evidence becoming stale under an explicit staleness rule.

These are review triggers, not truth decisions. A direction reversal is counter-evidence to inspect, not an automatic negation of the hypothesis. Sparse evidence can remain a low-confidence seed without being promoted or punished.

## 6. Reviews keep maintenance bounded

Personal-pattern maintenance reuses LifeOS review semantics instead of creating another obligation queue.

Weekly review may surface a bounded set of patterns that actually need attention, such as `needs-review` items, due items, materially changed evidence, unresolved contesting evidence, or new seeds. Quiet active patterns do not appear merely because they exist.

Daily review is even more conservative. Personal patterns appear only when the caller or workspace explicitly marks stable IDs as urgent or pinned. LifeOS does not infer urgency from free-form text.

Review decisions remain evidence-fingerprint scoped. Dismissing one review context does not suppress a later materially different evidence state forever.

## 7. Context uses patterns as evidence, never instructions

Relevant reviewed patterns can appear in bounded LifeOS context and reflection surfaces. Their typed context explicitly marks them as `evidence-not-instruction` and `can_authorize_mutation: false`.

Lifecycle meaning stays visible:

- active → `reviewed-working-hypothesis`;
- seed → `exploratory-hypothesis`;
- needs-review → `uncertain-needs-review`;
- archived → `archived-history` only when history is explicitly relevant.

A pattern that says “always do X” therefore does not become policy merely because the sentence exists in canonical Markdown. Direct pattern-driven planner scoring, ranking, duration changes, energy changes, or motivation changes are outside Phase 17.

## 8. Inspect and maintain the model in Obsidian

Open the **Personal Model** workspace from its ribbon button or command-palette command. The workspace groups hypotheses into **Needs review**, **Active**, **Seeds**, and **Archived** views and keeps the statement, qualitative confidence, evidence health, review timing, source versions, and evidence changes visible.

Actions such as Track, Adopt, Revise, Contest, and Archive create proposal previews rather than directly editing canonical pattern Markdown. Source links open canonical evidence; moved evidence can resolve to its unique current location while the reviewed path and hash remain visible.

For keyboard behavior, proposal-preview details, stale-target handling, and workspace recovery controls, see the focused [Personal Model workspace](personal-model.md) guide.

## 9. Rebuild disposable state safely

The following are not the only copy of Personal Model knowledge:

- `.lifeos/personal-model/` generations;
- the SQLite registry;
- retrieval indexes;
- graph state;
- generated workspace views.

You may remove disposable `.lifeos/` state and rebuild. Recognized `patterns/*.md` files remain canonical. A rebuild rereads those artifacts and recomputes factual diagnostics.

Existing arbitrary Markdown under `patterns/` is conservative by default. Only files declaring the recognized `pattern_schema` contract are treated as canonical Phase 17 patterns. Legacy-looking or user-authored notes without that contract are not silently converted, assigned a status, assigned a confidence class, or rewritten. Phase 17 has no general “guess what this old note meant” migration. A migration preview is appropriate only if a future recognizable legacy contract can be identified deterministically.

## 10. Local MCP and authenticated home-node boundaries

Local STDIO MCP exposes the bounded Personal Model proposal helpers. They produce drafts and preserve the same evidence, privacy, and proposal rules as the rest of LifeOS.

An authenticated home node may expose the same draft-producing helpers, but remote clients do not receive `proposal_approve` or `proposal_apply`. Remote assistance can prepare something for human review; it cannot accept a personal interpretation on your behalf.

Protected and excluded paths remain governed by retrieval policy. A hidden pattern must not become a content, path, hash, or duplicate-ID oracle merely because another client asks about the Personal Model.

## 11. What Phase 17 deliberately does not do

The shipped Personal Model does not:

- maintain a canonical generated personality biography;
- create a universal productivity, wellness, readiness, or life score;
- diagnose medical or psychological conditions;
- infer immutable traits;
- treat correlations as causes;
- auto-promote seeds to active hypotheses;
- auto-resolve contradictory evidence;
- silently rewrite arbitrary Markdown under `patterns/`;
- let an agent approve or apply its own semantic proposal;
- directly change planner ranking from a personal pattern.

The result is deliberately modest: LifeOS can remember what you currently think might be useful about your own experience, show exactly why that interpretation exists, notice when its evidence deserves another look, and keep you in control of whether the hypothesis changes.

## Related guides

- [Personal Model workspace](personal-model.md) for the detailed Obsidian controls.
- [Personal-pattern review triggers](personal-pattern-review-triggers.md) for deterministic re-evaluation semantics.
- [MCP Exploration and Controlled Mutation](15-mcp-exploration.md) for agent-facing exploration and proposal boundaries.
- [First-Class Daily and Weekly Reviews](10-first-class-reviews.md) for review continuity and decisions.

---

[← Previous: Evidence-Grounded Research](18-evidence-grounded-research.md) · [Manual home](README.md)
