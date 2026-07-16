[← Adaptive Planning](08-adaptive-planning.md) · [Manual home](README.md) · [Next: First-Class Reviews →](10-first-class-reviews.md)

# Goal-to-Plan Copilot

The goal-to-plan copilot helps turn a direction into a small, reviewable planning
choice. It is not an automatic obligation generator. A session may produce a
plan, a bounded experiment, a link to an existing plan, a parked decision, or no
plan at all.

Canonical goals and plans remain ordinary Markdown. Context previews, planning
sessions, model responses, comparisons, and workspace drafts cannot directly
rewrite them. Consequential changes enter the existing proposal lifecycle and
still require separate review, submission, approval, and application.

## Goal, experiment, or plan?

Use a **goal** for a direction whose value may outlast any particular method.
Examples include learning cell biology, building better coordination, or
maintaining a durable writing practice.

Use an **experiment** when uncertainty is the main obstacle and a cheap,
reversible test can create evidence. An experiment may be better than a plan
when you do not yet know whether a routine fits, a prerequisite is present, or
an approach is worth continuing.

Use a **plan** when the desired change is visible enough to define outcomes,
boundaries, evidence of success, and a near-term review wave. A plan does not
need to predict the whole journey.

Choose **Park**, **Continue Reflecting**, or **Abandon** when adding structure
would create more noise than clarity. These are complete session outcomes, not
errors.

## Starting the workspace

Open the copilot from one of these Obsidian entry points:

1. Open a goal note and run **Plan from Active Goal Note**.
2. Continue a quick capture into goal planning.
3. Open a goal or plan review from the weekly review.
4. Run **Open Goal-to-Plan Copilot** from the command palette.

The workspace uses the local typed Python bridge. Restarting the plugin or
bridge does not erase the durable planning session. Reopen the workspace and
resume by session ID.

## Context preview and privacy controls

Before option generation, inspect **Preview Planning Context**. Each included
item shows its path, stable identifier when available, content hash, inclusion
reason, excerpt, truncation state, redactions, freshness, and whether it was
explicitly selected.

You can:

- include a specific Markdown note;
- exclude an otherwise relevant note;
- redact chosen terms before model invocation;
- inspect omitted or truncated sources;
- continue with a smaller context pack;
- stop without creating a plan.

Sensitive roots such as journals, health, finance, relationships, and profile
notes are denied by default. They require both an allowed policy scope and an
explicit inclusion. A denial is reported as an omission rather than silently
bypassed.

Context is bounded by per-item and total byte limits. A source changed after the
preview is marked stale, and generation must restart from current canonical
state.

## Clarification sessions

The deterministic readiness check looks for visible identity, purpose, desired
change, horizon, constraints, contradictions, and existing-plan coverage.
Missing information remains unknown.

Clarification presents one visible question at a time. For each question, you
may:

- answer it;
- mark it unknown;
- skip it;
- mark it not relevant;
- park or abandon the session;
- choose an experiment;
- continue reflecting without a plan.

An optional model adapter may suggest a bounded question, but the suggestion is
validated before display. Invalid, unavailable, or timed-out model output falls
back to deterministic behavior. Hidden reasoning is not stored. The session
contains only visible questions, answers, decisions, hashes, references,
revision numbers, and proposal links.

## Comparing plan options

A ready session produces zero to three options. Meaningful alternatives must
differ in strategy, scope, pace, or uncertainty posture rather than wording.
Each option shows:

- desired outcome;
- scope boundaries and non-goals;
- assumptions and their sources;
- evidence of success;
- risks and tradeoffs;
- review date;
- milestones;
- unresolved questions;
- reasons the option may not fit;
- rejected alternatives and confidence label.

Use **Compare Plan Options** to inspect explicit dimensions rather than a hidden
quality score. No option is automatically selected. Existing active plans and
near-duplicates are surfaced so you can link or review them instead of creating
parallel work by accident.

## Milestones and rolling-wave actions

The selected option is decomposed with rolling-wave depth:

- **Current wave:** concrete actions for the next review interval, normally
  seven to fourteen days.
- **Next wave:** milestone outcomes and dependencies, without false task-level
  precision.
- **Later waves:** coarse outcomes that will be decomposed again from current
  evidence.

You may edit the draft title, desired outcome, milestone wording, action title,
duration, inclusion, and selected goal fields. Excluding an action or milestone
changes only the draft. Saving the workspace stores disposable session state,
not canonical Markdown.

## Capacity and conflict findings

Capacity checking compares the draft with visible active plans, explicit
available time, protected routines, blockers, due dates, recurring workloads,
and optional adaptive duration estimates.

The result keeps separate views:

- baseline declared durations;
- optional adaptive durations;
- protected commitments;
- existing-plan workload;
- proposed workload;
- missing duration or capacity values;
- conflict evidence and possible adjustments.

Exercise, rest, diet, relationships, and hobbies may be protected commitments.
They are not compressed into one productivity or life score. Missing data stays
unknown. Overload findings offer choices such as reducing the first wave,
extending the horizon, pausing a selected plan, running an experiment, or
keeping the goal unplanned.

## Explanations and assumptions

Open **Why this plan?** to inspect:

- which canonical facts and context references support the option;
- which assumptions came from the user, a note, deterministic logic, or an
  adapter;
- how milestones and actions connect to the desired outcome;
- capacity and conflict evidence;
- contradictions and omissions;
- counterfactual changes that would alter the fit result.

Counterfactual capacity is recalculated by the deterministic capacity service.
It is not improvised prose. Explanations do not claim that the plan is optimal
or that following it improves health, happiness, or worth.

## Creating and applying a proposal

Choose **Create Reviewable Proposal** after editing the draft. The proposal
contains exact source hashes and typed operations for the new plan, optional goal
link, selected goal updates, and explicit pause or supersession edits.

The plan is not created yet. Open **LifeOS → Proposals** and perform the normal
sequence:

1. Inspect the exact operations and review digest.
2. Submit for review.
3. Approve the unchanged digest.
4. Apply the proposal.

A concurrent goal or plan edit makes the proposal stale. Reopen the copilot from
the current canonical note and create a new proposal. Never force-apply an old
planning snapshot.

Interrupted application uses the shared transaction and recovery journal. Open
**System Health → Recovery** and allow LifeOS to finish or restore the
transaction before applying another proposal.

## Goal review and replanning

Daily attention and weekly review may offer a copilot review when visible
evidence shows:

- an active goal has no active plan;
- a plan has no feasible next action;
- a milestone is complete and the next wave is still coarse;
- repeated partial, skipped, or deferred attempts need clarification;
- constraints, capacity, deadlines, scope, or prerequisites changed;
- assumptions are stale;
- a review date is approaching or overdue.

A living review starts from current canonical state. It can compare the original
option when available, the current plan, execution evidence, explicit
corrections, and recent review answers. Execution history may prompt a question,
but it cannot rewrite intent.

Available outcomes are:

- continue unchanged;
- adjust the next wave;
- revise scope;
- split or merge;
- pause;
- supersede;
- close;
- return to an experiment;
- reopen goal clarification.

Consequential outcomes create proposals. Continue unchanged creates no proposal.
Superseded plans remain in the vault, and applied review decisions append visible
decision lineage. Dismissing a review suggestion suppresses only its exact
evidence fingerprint. Materially new evidence may surface it again.

## Offline and no-model operation

The core workflow remains usable without a model:

- readiness diagnostics;
- context preview and privacy enforcement;
- deterministic clarification questions;
- one focused fallback option;
- rolling-wave decomposition;
- capacity and conflict checks;
- explanations and counterfactuals;
- proposal creation and lifecycle;
- attention, weekly review, and replanning triggers.

Model-assisted behavior is optional and provider-neutral. No provider-specific
repository file is required. A missing adapter, timeout, or invalid response does
not block ordinary vault use.

## Troubleshooting

### The goal is not ready

Inspect readiness findings. Answer only what helps. Unknown, experiment, park,
continue reflecting, and no-plan remain valid choices.

### An existing plan is reported

Open the referenced plan and review whether it already covers the desired
outcome. Link or replan it before creating another active plan.

### Context was denied

Inspect the omission. Continue without the source, explicitly include an allowed
source, or change the local sensitive-scope policy. The copilot does not bypass
the denial.

### Model output was rejected

The response exceeded the schema, referenced unknown evidence, produced cosmetic
options, or violated a safety boundary. Retry or continue with deterministic
fallback.

### The source became stale

Reload the goal or plan, rebuild context, and restart the affected comparison or
proposal from the new hash.

### The bridge restarted

Resume the durable session. Unsaved visual state may need to be reopened, but
canonical Markdown and published proposals remain untouched.

### Proposal recovery is required

Open **System Health → Recovery**. Do not delete transaction folders manually.
Complete recovery before another application.

## Removal and reversibility

Disable the plugin and remove `.lifeos/planning-sessions/`,
`.lifeos/replanning/`, or the whole `.lifeos/` directory to delete disposable
copilot state. This does not delete canonical goals, plans, proposals, execution
history, or applied decision lineage.

The remaining files are ordinary Markdown and remain readable without the
copilot. Reinstalling or rebuilding the registry discovers them again.

## Current limitations

The copilot is desktop-first and has no mobile parity. It cannot infer unrecorded
physical-world events, prove why a task was avoided, or determine that a goal is
invalid. Context relevance and model suggestions may be incomplete. Capacity
checks depend on visible inputs. The workflow deliberately favors reversible,
inspectable planning over autonomous optimization.

[← Adaptive Planning](08-adaptive-planning.md) · [Manual home](README.md) · [Next: First-Class Reviews →](10-first-class-reviews.md)
