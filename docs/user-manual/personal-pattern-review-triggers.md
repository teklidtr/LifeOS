[← Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md)

# Personal-pattern review triggers

LifeOS treats every canonical personal pattern as a working hypothesis. A review trigger means **this hypothesis deserves another look**. It does not mean that LifeOS has proved the pattern true or false, changed your confidence, or adopted a new interpretation for you.

## What can trigger a review

For every canonical pattern, LifeOS can compare the exact reviewed evidence references with current factual source state. Review attention can be recommended when reviewed evidence has changed, moved, disappeared, been deleted, become ambiguous, or when the stored evidence references no longer match the last reviewed evidence fingerprint. A configured `review_due_at` time can also trigger review.

Patterns with a supported deterministic `evaluation` recipe can additionally reuse the cautious observation analysis already used by `lifeos observe patterns`. The initial recipe kinds are:

```yaml
evaluation:
  kind: numeric-metric-association
  parameters:
    outcome: morning_energy
    factor: sleep_hours
    min_samples: 8          # optional; default is 5
    stale_after_days: 30    # optional
```

and:

```yaml
evaluation:
  kind: activity-outcome-comparison
  parameters:
    outcome: evening_energy
    activity: weight-training
    min_samples: 5          # optional; default is 3 per group
    stale_after_days: 30    # optional
```

A deterministic recipe can recommend review for new usable dated observations, weaker evidence, an aggregate direction reversal, an optional staleness threshold, or the ordinary factual evidence-state and due-date reasons above. Unknown recipe kinds and unsupported recipe parameters fail closed instead of being guessed.

## How the old and new analyses are compared

LifeOS does not store a hidden second copy of the old analysis. When possible, it reconstructs the reviewed analysis from the journal evidence whose exact reviewed content is still identifiable. An unchanged source can be reused. A same-hash source that merely moved can also be reused at its current path.

If a reviewed journal source changed, disappeared, was deleted, or became ambiguous, LifeOS cannot reconstruct those historical bytes from the current vault. In that case it reports the factual source problem and avoids pretending that it can make a clean old-versus-new statistical comparison.

New dated observations that enter the recipe after the last review are reported as materially new evidence. If a reconstructable reviewed candidate later disappears or drops to a lower evidence-strength class, LifeOS reports weaker evidence. If the aggregate direction reverses, LifeOS reports the reversal as counter-evidence to the previously reviewed direction.

**Counter-evidence is not a verdict.** A reversal says that the current deterministic result points the other way. It does not diagnose you, establish causation, or automatically declare the working hypothesis false. Likewise, no new observations is not evidence against a pattern, and missing evidence remains unknown rather than negative evidence.

## Canonical patterns versus the derived Personal Model

The durable hypothesis always lives in its human-readable `patterns/*.md` file. That canonical file owns the statement, lifecycle status, confidence, reviewed evidence references, review timing, origin, and human reflection.

LifeOS can rebuild a lightweight aggregate index under `.lifeos/personal-model/`. The derived Personal Model groups unique healthy patterns into Active, Seeds, Needs review, and Archived views and records inspectable metadata such as stable pattern ID, canonical path and content hash, title and description, confidence, review reasons, origin, review-due state, evidence health, evidence diagnostics, and deterministic freshness when an evaluation recipe can establish it.

The derived index is a map, not another source of truth. It does not create `profile/personal-model.md`, does not generate a personality narrative, and does not assign a hidden life, wellness, readiness, or productivity score. It also does not copy the pattern's human reflection into the index. To inspect or change the actual hypothesis, follow the canonical pattern path.

Evidence health is deliberately categorical rather than scored:

- `none`: the pattern declares no reviewed evidence references;
- `healthy`: every reviewed reference still resolves to the exact reviewed version;
- `attention`: a reviewed source moved or changed and deserves inspection;
- `unavailable`: one or more reviewed sources are missing, deleted, ambiguous, or otherwise cannot be established safely.

Malformed declared patterns and duplicate stable IDs do not disappear and do not masquerade as healthy entries. They appear as diagnostics while unaffected unique patterns remain inspectable. Ordinary Markdown under `patterns/` without a recognized pattern schema remains ordinary user content and is ignored by the Personal Model index.

Deleting `.lifeos/personal-model/` deletes only disposable derived state. Rebuilding rereads canonical patterns and recomputes the same typed view and evidence diagnostics; deleting the index cannot delete, downgrade, archive, or rewrite a canonical hypothesis.

## What LifeOS does not do automatically

Running review assessment is read-only. It does not rewrite the pattern statement, lifecycle status, confidence, evidence list, evidence fingerprint, or human reflection. Manual or semantic patterns without a deterministic recipe receive only factual evidence-state, fingerprint, and timing checks; LifeOS does not launch a vault-wide psychological contradiction search.

A review recommendation also does not silently change `seed` or `active` to `needs-review`. Creating that change is a separate explicit action and produces the ordinary draft proposal. The proposal is bound to the exact pattern version that was assessed, so an intervening edit makes the assessment stale and requires re-evaluation. Submission, approval, rejection, application, authorization, and recovery still use the normal proposal lifecycle.

Archived patterns may still have factual diagnostics when inspected, but they are excluded from routine review recommendations.

## Current integration boundary

LIFEOS-1704 provides the deterministic Python assessment and explicit draft-proposal boundary. LIFEOS-1705 adds the rebuildable Python Personal Model read model and crash-consistent disposable index under `.lifeos/personal-model/`. Neither task adds a standalone CLI, MCP, or Obsidian Personal Model screen. Bounded daily/weekly review integration, context integration, and the Obsidian workspace remain later Phase 17 layers that consume these Python contracts rather than reimplementing their rules.

---

[← Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md)
