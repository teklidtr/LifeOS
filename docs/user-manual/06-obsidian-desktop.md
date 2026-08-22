[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)

# Obsidian Desktop Cockpit

Obsidian is the normal LifeOS interface. The local Python engine starts automatically and
performs every validated read or write. The CLI remains a recovery and developer interface.

## First run

1. From the LifeOS repository root, build the bundled plugin:

   ```bash
   npm --prefix packages/obsidian-plugin ci
   npm --prefix packages/obsidian-plugin run build
   ```

2. Install the three release files into the vault:

   ```bash
   mkdir -p /absolute/path/to/LifeOS-vault/.obsidian/plugins/lifeos
   cp packages/obsidian-plugin/build/{main.js,manifest.json,styles.css} \
     /absolute/path/to/LifeOS-vault/.obsidian/plugins/lifeos/
   ```

   Do not copy `dist-test/src/index.js` as `main.js`. It is unbundled controller
   test output, not an Obsidian entry point.

3. In **Settings → Community plugins**, enable **LifeOS**.
4. Open **LifeOS Settings**. Choose the absolute `lifeos.yml` path and the
   repository environment's Python executable, for example
   `/absolute/path/to/lifeos/.venv/bin/python`, then set your local actor ID.
5. Enable **Start on load**, click **Restart bridge**, and open the LifeOS ribbon
   view. The connection indicator should show **Connected**.

## Today

The **Today** view combines check-in state, proposed actions, due study work, active
experiments, inbox captures, proposals, attention items, and serious diagnostics. Change
available time, energy, motivation, or mode to refresh the deterministic menu.

Use **Quick Capture** for thoughts, plan tasks, project seeds, journal observations,
flashcards, and metrics. Use **Start**, **Complete**, **Partial**, **Skip**, **Defer**, or
**Cancel** to record what actually happened. Silence remains **unaccounted**, never skipped.

## Attention and reconciliation

Attention cards explain their evidence and offer bounded actions. **Ask tomorrow** snoozes
an item; **Dismiss** hides that stable item; **Stop tracking** changes the routine rather
than blaming the user. Optional background notifications use generic text by default.

## Goal-to-plan copilot

From an active goal note, run **Plan from Active Goal Note**, or open **Open
Goal-to-Plan Copilot** from the command palette. The workspace lets you preview
and redact context, answer one clarification at a time, compare plan options,
edit rolling-wave actions, inspect capacity and provenance, and create a normal
reviewable proposal. Existing active plans are surfaced before another plan is
created. See [Goal-to-Plan Copilot](09-goal-to-plan-copilot.md) for the complete
workflow and privacy controls.

## Knowledge conversations

Open **Knowledge Conversation** from the ribbon, command palette, active note,
selection, folder, or tag. Inspect and refine the scope before asking. Evidence
cards expose ranking signals and open the exact note section. Pin useful sources,
exclude irrelevant ones, use evidence-only mode, or branch from a saved turn.

Index health and provider disclosure remain visible. Missing generation falls back
to local retrieval, while stale evidence and malformed citations are labelled
explicitly. Converting an answer into a note, section, link, question, claim,
flashcard, or contradiction always opens a proposal preview. See [Semantic
Retrieval and Knowledge Conversations](11-semantic-retrieval-and-knowledge-conversations.md).


## Reviews and proposals

Use **Open Today's Review**, **Open This Week's Review**, **Open Active Review
Artifact**, or **Open Review History**. Daily and weekly reviews are canonical
Markdown notes with durable phases, answers, decisions, continuity, and human-owned
reflection. Refresh replaces managed evidence only and rejects concurrent edits.

Review suggestions that affect another canonical note create ordinary draft proposals.
Run **Open Proposals** from the command palette to open the dedicated proposal
workspace. Proposals are grouped by lifecycle state. Select one to inspect its
rationale, body, source paths, ordered operation targets, GitHub-style red/green
line diffs, Python-computed review digest, and validation findings. The diff is a
review view of the canonical typed operations; it does not replace or edit them.

Use **Accept changes** on a draft, pending, or approved proposal and confirm once.
Python executes only the remaining lifecycle transitions, reloading and checking
the reviewed digest between them; application still validates current target
hashes before changing canonical Markdown. Pending or approved proposals may be
**Rejected**. If the proposal changed after review, acceptance fails without
applying it. See [First-Class Daily and Weekly Reviews](10-first-class-reviews.md).

When a generated file has been manually deleted but its durable ownership record
remains, the same workspace shows an **Ownership recovery** card. Compare the
recorded SHA-256, generator, and timestamps. Choose **Restore instructions** when
you have reviewed file bytes to put back at the exact path; the card does not guess
or recreate content. Choose **Create release proposal** when the deletion was
intentional. Review the resulting red-line manifest diff and use **Accept changes**
to release ownership. Creating the draft alone does not change ownership, and
Refresh does not resolve or hide the orphan.

## Personal experiments

Open **Personal Experiments** from the ribbon, command palette, or a relevant goal,
plan, task, capture, review, conversation, or experiment note. The workspace covers
design, warning acknowledgment, baseline and active tracking, observations, pause
and resume, amendments, deterministic analysis, evidence inspection, history,
proposals, migration, and recovery. Safety blocks and stale edits are explicit. See
[Personal Experiments](12-personal-experiments.md).


## Rich capture

Use the camera ribbon icon or the commands **Open Rich Capture**, **Quick Capture
Meal**, **Quick Capture Exercise**, **Capture Selected Text**, and **Open Active
Rich Capture**. The standard controller can save and edit canonical capture
Markdown, import and audit original files, run local extraction jobs, decide
suggestions, link records, merge or split, preview provider context, create
proposals, and rebuild derived state.

The codebase also defines paste, drag-and-drop, folder-drop, mobile-share, review,
experiment, conversation, goal, plan, task, habit, and diary origins. These are
not all registered as platform handlers in the standard plugin. Likewise, the
controller defines timeline, gallery, queue, chart, mobile, focus, and shortcut
state, but a host renderer must turn those models into visible controls. Provider
OCR, transcription, and nutrition or image enrichment are not wired to the
standard processing button, which currently runs local extraction. See [Rich
Capture](13-rich-capture.md) for the exact current surface.

[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)
