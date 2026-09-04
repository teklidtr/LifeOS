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

## What LifeOS does not do automatically

Running review assessment is read-only. It does not rewrite the pattern statement, lifecycle status, confidence, evidence list, evidence fingerprint, or human reflection. Manual or semantic patterns without a deterministic recipe receive only factual evidence-state, fingerprint, and timing checks; LifeOS does not launch a vault-wide psychological contradiction search.

A review recommendation also does not silently change `seed` or `active` to `needs-review`. Creating that change is a separate explicit action and produces the ordinary draft proposal. The proposal is bound to the exact pattern version that was assessed, so an intervening edit makes the assessment stale and requires re-evaluation. Submission, approval, rejection, application, authorization, and recovery still use the normal proposal lifecycle.

Archived patterns may still have factual diagnostics when inspected, but they are excluded from routine review recommendations.

## Current integration boundary

LIFEOS-1704 provides the deterministic Python assessment and explicit draft-proposal boundary. It does not add a new standalone CLI, MCP, or Obsidian review screen. The derived Personal Model, bounded daily/weekly review integration, context integration, and Obsidian workspace are later Phase 17 layers that consume this same read-only assessment contract rather than reimplementing its rules.

---

[← Feature Breakdown](03-feature-breakdown.md) · [Manual home](README.md)
