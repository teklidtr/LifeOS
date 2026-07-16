[← Goal-to-Plan Copilot](09-goal-to-plan-copilot.md) · [Manual home](README.md) · [Next: Semantic Retrieval →](11-semantic-retrieval-and-knowledge-conversations.md)

# First-Class Daily and Weekly Reviews

LifeOS reviews are canonical Markdown artifacts, not temporary questionnaires.
You can open them directly in Obsidian, write reflection in ordinary Markdown,
close the plugin, remove disposable runtime state, and resume later without
losing progress.

A daily review lives at:

```text
reviews/daily/YYYY-MM-DD.md
```

One daily artifact contains both **morning** and **evening** phases. A weekly
review lives at:

```text
reviews/weekly/YYYY-Www.md
```

Weekly identity follows the ISO week, with an explicit Monday-to-Sunday period
stored in frontmatter.

## Open a review in Obsidian

Use one of the review workspace commands:

- **Open Today's Review** creates or resumes today's daily artifact.
- **Open This Week's Review** creates or resumes the current ISO-week artifact.
- **Open Active Review Artifact** loads the review note currently open in
  Obsidian.
- **Open Review History** shows earlier daily and weekly artifacts.

The workspace is a view over the Markdown file. It does not replace the file.
Use **Open canonical review Markdown** whenever you want to edit the artifact as
an ordinary note.

## Managed evidence and human reflection

Each review contains four managed blocks:

- review facts;
- review items;
- continuity;
- completion summary.

LifeOS may refresh only the text inside these marked blocks. Morning, evening,
weekly, and general notes remain human-owned. A refresh verifies the content
hash first and refuses to overwrite a concurrent Obsidian edit.

Missing evidence is shown as empty or unavailable. It is not interpreted as
failure, avoidance, low motivation, or any other personal conclusion.

## Daily review flow

The morning phase provides a bounded orientation rather than an automatic task
assignment. Typical prompts ask what deserves protection, what is known about
capacity, and what is intentionally not for today.

The evening phase reconciles explicit check-ins, task outcomes, attention
items, and unfinished loops. It can be completed even when the morning phase
was intentionally skipped. Silence remains unaccounted, not silently converted
into a skipped or failed action.

For each phase you may:

- complete a section;
- intentionally skip a section;
- reopen a section;
- answer a reflection prompt;
- complete or skip the phase;
- leave the phase incomplete and resume later.

The daily artifact is complete only when its phases have been explicitly
resolved according to the review rules.

## Weekly review flow

The weekly artifact gathers bounded evidence for the ISO week, including:

- explicit execution and unfinished loops;
- goals or plans that may need review;
- adaptive-planning findings;
- experiments and observations;
- inbox captures and proposals;
- study load and system diagnostics.

Generated evidence may prompt a question, but it cannot claim why something
happened. Write themes, corrections, changed constraints, and next orientation
inside the human-owned weekly reflection sections.

## Item decisions and continuity

A review item decision is attached to the exact evidence fingerprint displayed
in the artifact. Available decisions include acknowledge, carry, clarify,
defer, dismiss for this review, open source, and propose change.

The next artifact can show unresolved or carried decisions from the previous
review. An unchanged dismissed fingerprint remains suppressed. Materially
changed evidence may surface again. This avoids both duplicate obligations and
permanent suppression of a changed situation.

History links make previous and next artifacts navigable. Completing a review
does not erase it or flatten its reflection into a summary score.

## Proposal-gated changes

A review may suggest changing a goal, plan, task, capture, or other canonical
note. Such a suggestion does not edit the target directly. **Create proposal**
produces a normal draft proposal tied to:

- the review ID;
- item ID;
- evidence fingerprint;
- exact target content hash;
- requested typed change;
- user-visible rationale.

The target changes only after the existing submit, approve, and apply sequence.
A stale target or changed evidence rejects the operation. Continue unchanged,
acknowledge, carry, and reflection-only outcomes do not require proposals.

## Refresh, stale state, and recovery

A stale state means the Markdown artifact changed after the workspace loaded it.
Reload the artifact, preserve the newer human edit, and retry. Do not replace the
file with an older workspace copy.

A blocked state usually means one of these conditions:

- unsupported review schema;
- duplicate review identity;
- malformed frontmatter;
- missing or duplicated managed boundaries.

Open the linked Markdown file and follow the diagnostic. LifeOS fails closed
rather than guessing how to merge an ambiguous artifact.

## Legacy review migration

Legacy files are detected at these paths:

```text
reviews/morning-YYYY-MM-DD.md
reviews/evening-YYYY-MM-DD.md
reviews/weekly-YYYY-Www.md
```

Migration is always previewed. Morning and evening reflections are grouped into
one daily artifact, while weekly identity is preserved. The preview reports
malformed files, target collisions, and source hashes.

Applying migration:

1. verifies that every legacy source still matches the previewed hash;
2. creates or resumes only a pristine canonical target;
3. copies human reflection into labelled imported sections;
4. records every source in `migrated_from`;
5. leaves all legacy files untouched.

Archive or delete legacy files only after independently reviewing the new
artifact.

## Rebuild and removal

Review progress, answers, decisions, lifecycle state, and continuity live in
Markdown frontmatter. Files under `.lifeos/reviews/` are disposable indexes and
idempotency caches.

After deleting `.lifeos/`, use **Rebuild review indexes** from the review
workspace or reinstall/start LifeOS and run the rebuild action. LifeOS reads the
canonical artifacts and recreates progress and history indexes.

Disabling the plugin leaves readable Markdown. Managed comments become inert,
and every reflection, decision, proposal reference, and migration lineage
remains available in Obsidian or any text editor.

## Privacy and model behavior

First-class reviews work without a configured model. Snapshot generation,
progress, migration, continuity, history, and proposals are deterministic.
Review artifacts do not widen model permissions and do not automatically send
journal, health, relationship, finance, or profile notes to an adapter.

## Current limitations

The review workspace is desktop-first and has no mobile parity. LifeOS can
summarize only recorded evidence. It cannot infer unrecorded physical-world
work, diagnose motivation, or determine whether a personal direction is good.
Long histories remain queryable, but Obsidian presentation may still need
additional filtering and visualization in later releases.

[← Goal-to-Plan Copilot](09-goal-to-plan-copilot.md) · [Manual home](README.md) · [Next: Semantic Retrieval →](11-semantic-retrieval-and-knowledge-conversations.md)
