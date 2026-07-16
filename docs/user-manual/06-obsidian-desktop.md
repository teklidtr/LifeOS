[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)

# Obsidian Desktop Cockpit

Obsidian is the normal LifeOS interface. The local Python engine starts automatically and
performs every validated read or write. The CLI remains a recovery and developer interface.

## First run

1. Install the plugin folder containing `manifest.json`, `main.js`, and `styles.css` into
   `.obsidian/plugins/lifeos/`.
2. In **Settings → Community plugins**, enable **LifeOS**.
3. Open **LifeOS Settings** and choose **lifeos.yml**, the trusted Python executable, and
   your local actor display name.
4. Enable **Start LifeOS when Obsidian opens**.
5. Click the LifeOS ribbon icon. The connection indicator should show **Connected**.

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
Proposal screens show exact operations and a Python-computed digest. **Approve** and
**Apply** require separate explicit confirmations. A changed proposal invalidates the UI
review immediately. See [First-Class Daily and Weekly Reviews](10-first-class-reviews.md).

## Personal experiments

Open **Personal Experiments** from the ribbon, command palette, or a relevant goal,
plan, task, capture, review, conversation, or experiment note. The workspace covers
design, warning acknowledgment, baseline and active tracking, observations, pause
and resume, amendments, deterministic analysis, evidence inspection, history,
proposals, migration, and recovery. Safety blocks and stale edits are explicit. See
[Personal Experiments](12-personal-experiments.md).


[← Workflow](05-workflow.md) · [Manual home](README.md) · [Next: Troubleshooting →](07-troubleshooting.md)
