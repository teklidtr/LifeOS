[← Previous: Setup & Installation](04-setup-and-installation.md) · [Manual home](README.md) · [Next: Obsidian Desktop →](06-obsidian-desktop.md)

# 5. Step-by-Step Usage Instructions (The Workflow)

This chapter explains how to operate LifeOS across three timeframes:

1. entering data at the moment it appears;
2. running a light daily routine;
3. performing a deeper weekly review.

## 5.1 Entering data

### Capture a new thought on the fly

1. **Open Obsidian.**
2. **Create a note under `raw/`.**
3. Use a timestamp or descriptive filename:

   ```text
   raw/2026-07-16-idea-about-study-fatigue.md
   ```

4. Add minimal frontmatter:

   ```md
   ---
   type: raw
   title: Idea About Study Fatigue
   description: A quick observation about why long reading sessions may fail.
   status: inbox
   confidence: low
   review_reasons:
     - Process during weekly review
   ---

   I may not dislike studying itself. The problem may be switching from reading
   to recall too late, after attention has already declined.
   ```

5. Save the note and return to what you were doing. Do not stop to perfect the
   ontology during capture.


### Capture a meal, workout, or file

Use the camera ribbon icon or one of the Rich Capture commands when the original
evidence matters or when a record should participate in reviews, retrieval, or
experiments.

1. Choose **Open Rich Capture**, **Quick Capture Meal**, or **Quick Capture
   Exercise**.
2. Enter a sentence and correct the event time when needed.
3. Save the canonical note before adding optional processing.
4. Attach regular files, then run local extraction when useful.
5. Confirm, correct, or reject suggestions and add explicit links.
6. Use a proposal for any change to a task, plan, habit, goal, note, reminder, or
   calendar artifact.

Use `raw/` for a lightweight thought that needs no file manifest or rich-capture
lifecycle. Use `captures/` when preserving original bytes, provenance, uncertain
values, attachment integrity, or cross-workflow evidence matters. See
[Rich Capture](13-rich-capture.md) for current plugin availability and limits.

### Capture a task

Tasks should normally live inside the relevant plan.

1. Open the appropriate note under `plans/`.
2. Add an entry to its `tasks` list:

   ```yaml
   - task_id: biology-test-active-recall
     title: Test a 25-minute active-recall session
     status: todo
     duration: 25
     energy: medium
     motivation: low
     mode: study
     due: 2026-07-18
     blocked_by: []
   ```

3. Save the plan.
4. Run the daily planner to confirm that the task loads and is eligible.

### Capture a new project or medium-term outcome

1. Create a file under `plans/`.
2. State a clear desired outcome.
3. Link it to a broader goal.
4. Add only the next several concrete actions.

```md
---
id: plan-build-biology-foundation
type: plan
title: Build a Biology Foundation
status: active
goal: goal-understand-human-biology
desired_outcome: Complete six textbook chapters and create durable notes.
review_date: 2026-07-21
tasks:
  - task_id: biology-read-chapter-01
    title: Read chapter 1
    status: todo
    duration: 40
    energy: medium
    motivation: medium
    mode: reading
    blocked_by: []
---
```

Avoid planning an entire year at task-level resolution. Keep distant goals broad
and near-term work concrete.

### Capture a factual source

1. Save the material under `study/` or `raw/`.
2. Record its author, URL, edition, date, or citation.
3. Add your questions and disagreements.
4. Run `uv run lifeos scan`, or let the MCP-connected agent call
   `registry_refresh`, after adding the source.
5. Ask the MCP-connected agent to ingest the registered source into an explicit
   `wiki/` target. For an absent target, the agent synthesizes a grounded draft
   and calls `ingestion_create_wiki_proposal`. For an existing note, identify the
   one heading to update; the agent reads that target and calls
   `ingestion_update_wiki_section_proposal` with the heading text and replacement
   body. If both a detailed page and an existing-section update belong to the
   same ingestion, use `ingestion_create_wiki_and_update_section_proposal` so
   both operations remain in one atomic draft.
6. Review the resulting draft proposal. Ingestion does not submit, approve, or
   apply it.

### Capture a flashcard

1. Create a Markdown file under `flashcards/`.
2. Use `type: flashcard`.
3. Include a unique ID, topic, question, answer, due date, estimated time, and
   source references.
4. Keep one testable idea per card.
5. Run:

   ```bash
   uv run lifeos study review --minutes 5
   ```

This verifies that the card is valid and visible to the workload builder.

## 5.2 The daily routine

## Morning

### 1. Record your starting state

Create or open today's journal note:

```text
journal/2026-07-16.md
```

Record only variables you can use consistently:

```yaml
metrics:
  sleep_hours: 7.2
  morning_energy: 6
  motivation: 4
activities:
  - morning-sunlight
```

Do not fabricate precision. A consistent rough scale is more useful than a
complex scale abandoned after three days.

### 2. Check system health

Run:

```bash
uv run lifeos status
```

Pay special attention to:

- blocked recovery transactions;
- corrupt Markdown or ownership state;
- an unavailable registry;
- stale graph views;
- stale or damaged exports.

You do not need to rebuild every optional product immediately, but do not ignore
`blocked` or `corrupt` consequential state.

### 3. Build today's menu

Estimate available time, energy, motivation, and optional work mode honestly:

```bash
uv run lifeos plan today \
  --minutes 150 \
  --energy medium \
  --motivation low
```

Read both the selected and rejected candidates. Then choose what you intend to
do. The menu is advice, not a command.

### 4. Build today's study workload

```bash
uv run lifeos study review --minutes 20
```

Use a topic filter when you deliberately want a focused session:

```bash
uv run lifeos study review \
  --minutes 20 \
  --topic "Cell Biology"
```

### 5. Begin with the smallest meaningful action

Open the source plan and work from the canonical note rather than copying tasks
into a second application.

## During the day

### Capture interruptions without reorganizing immediately

Write new ideas to `raw/` or append them to today's journal. Processing can wait
until the evening or weekly review.

### Update task state

When an action is complete, change:

```yaml
status: todo
```

to:

```yaml
status: done
```

### Record meaningful deviations

When you skip a suitable task, record a short explanation:

```md
Skipped the writing task. Energy was adequate, but the task still felt
underspecified. The next action may need to be “outline the three sections.”
```

This is more useful than marking the day as a failure.

### Use context packs while thinking

Before asking an AI a vault-related question, build a context pack:

```bash
uv run lifeos context build \
  "What evidence do I have about why writing tasks are delayed?"
```

Review evidence gaps and omissions before trusting the answer.

## Evening

### 1. Complete the journal record

Add evening energy, major activities, exercise, unusual events, task outcomes,
and a short reflection.

### 2. Close task loops

For each task touched today:

- mark it done;
- leave it active;
- clarify the next action;
- add a blocker;
- adjust the due date when justified;
- archive it when it is no longer relevant.

Do not preserve zombie tasks merely because deleting them feels impolite.

### 3. Process important captures

Review both lightweight notes under `raw/` and canonical rich captures under
`captures/`. Rich captures may also need attachment audits, failed extraction
review, suggestion decisions, linking, merge or split, or archive.

A raw capture may become:

- a wiki note;
- a study question;
- a flashcard;
- a task inside an existing plan;
- a new plan;
- a journal observation;
- an experiment;
- nothing worth keeping.

Not every thought needs promotion.

### 4. Review proposals

In Obsidian, run **Open Proposals** from the command palette. Select each proposal
and inspect its source paths, body, exact typed operations, review digest, and
validation findings. Then move it through only the lifecycle steps you intend:

1. **Submit** a draft for review.
2. **Approve** the unchanged pending proposal.
3. **Apply** the unchanged approved proposal to canonical Markdown.

Approval and application require separate confirmations. Reject a pending or
approved proposal when it should not proceed.

For recovery or scripted inspection, list indexed proposals from the CLI:

```bash
uv run lifeos proposals list --status pending
uv run lifeos proposals list --status approved
```

The CLI provides listing and legacy lifecycle migration, not direct approval or
application. The Obsidian workspace calls the trusted Python authorization
boundary and does not implement lifecycle rules itself.

### 5. Rebuild derived products when useful

After meaningful vault changes:

```bash
uv run lifeos graph build knowledge
uv run lifeos export build public-wiki
```

Rebuilding every product every evening is optional. Status commands identify
stale generations.

## 5.3 The weekly review

Set aside approximately 30 to 90 minutes once per week.

### 1. Check the whole system

```bash
uv run lifeos status
```

Inspect individual derived products you use:

```bash
uv run lifeos graph status knowledge
uv run lifeos graph status provenance
uv run lifeos graph status personal-patterns
uv run lifeos graph status system

uv run lifeos export status public-wiki
uv run lifeos export status study-bundle
uv run lifeos export status trusted-agent
uv run lifeos export status personal-review
```

### 2. Process the capture inbox

Review recent files under `raw/` and decide whether each should be deleted,
journaled, promoted to wiki or study material, converted to a flashcard, attached
to a plan, turned into an experiment, or kept as a tentative pattern candidate.

Also inspect `captures/` for `needs-review` or `failed` states, unconfirmed
suggestions, missing or changed attachments, and extraction issues. Archive a
rich capture rather than deleting its evidence casually. Change `status: inbox`
on raw notes only after making the decision.

### 3. Review goals

Open `goals/` and ask:

- Is this still important?
- Is the reason still true?
- Is there an active plan supporting it?
- Has it become an obligation inherited from an older version of me?
- Should it be paused or archived?

Goals are directions, not task warehouses.

### 4. Review active plans

For every active plan:

1. Read the desired outcome.
2. Check completed actions.
3. Remove obsolete work.
4. Clarify vague actions.
5. Identify blockers.
6. Add only the next one or two weeks of concrete work.
7. Confirm the review date.
8. Ensure task IDs remain unique.

A useful next action is observable:

```text
Bad: Work on biology
Better: Read pages 45–62 and write five questions
```

### 5. Review study workload

Run a longer preview:

```bash
uv run lifeos study review --minutes 60
```

Look for overdue clusters, unclear questions, cards detached from source notes,
topics dominating the queue, and cards that test trivia rather than
understanding.

### 6. Review personal evidence

Run selected analyses only when you have enough comparable records:

```bash
uv run lifeos observe patterns \
  --outcome morning_energy \
  --factor sleep_hours \
  --min-samples 8
```

Ask whether units are consistent, definitions changed, data is missing
systematically, another event explains the result, and the effect is practically
meaningful.

### 7. Review knowledge gaps

Build context packs around active goals:

```bash
uv run lifeos context build \
  "What evidence is missing from my current cell biology understanding?"
```

Use evidence gaps to decide what to read or test next.

### 8. Review AI proposals

Open **Open Proposals** in Obsidian. For each proposal, submit, approve, apply, or
reject it through the explicit workspace controls; leave it unchanged or
regenerate it when its source has changed.
Never approve a proposal merely because its prose sounds confident.

### 9. Rebuild useful graph views

```bash
uv run lifeos graph build knowledge
uv run lifeos graph build provenance
uv run lifeos graph build personal-patterns
```

Use graph output to find isolated notes, missing connections, bridge concepts,
and sources with many derived outputs. Open the original notes before treating a
graph-discovered relationship as evidence.

### 10. Rebuild exports

Build only the products you use:

```bash
uv run lifeos export build public-wiki
uv run lifeos export build study-bundle
```

Verify that private, archived, malformed, or unsafe material is not included in
public output.

### 11. Refresh the disposable registry

After a week of manual edits, refresh the registry:

```bash
uv run lifeos scan
```

Use `--config /absolute/path/to/lifeos.yml` when the command is not run beside
the configuration file. An MCP-connected agent can perform the identical
refresh with `registry_refresh`.

### 12. Commit the canonical vault

From the vault:

```bash
git status
git diff
```

Commit a coherent weekly checkpoint:

```bash
git add journal raw wiki study flashcards goals plans patterns reviews system proposals
git commit -m "chore(vault): complete weekly review"
```

Do not commit `.lifeos/`.

### 13. End with a light plan

Choose one major direction, a few medium-sized outcomes, several eligible next
actions, and enough empty space for curiosity, recovery, and life's uninvited
plot twists.

The system should leave you with greater clarity, not the feeling that your
hobbies have formed a middle-management department.

### 14. Run a personal experiment

Open **Personal Experiments**, turn one question into a small protocol, inspect the
warning list, collect a baseline, and record observations without converting missing
values into zero. After collection, inspect the raw evidence and deterministic
descriptive analysis before recording a conclusion. Follow-up actions remain
reviewable proposals. See [Personal Experiments](12-personal-experiments.md).


---

[← Previous: Setup & Installation](04-setup-and-installation.md) · [Manual home](README.md) · [Next: Obsidian Desktop →](06-obsidian-desktop.md)
