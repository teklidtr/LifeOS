[← Semantic Retrieval and Knowledge Conversations](11-semantic-retrieval-and-knowledge-conversations.md) · [Manual home](README.md) · [Rich Capture →](13-rich-capture.md)

# Personal Experiments

Personal experiments help you learn from a deliberate change while keeping the
question, protocol, observations, uncertainty, and decisions together. They are
for disciplined self-observation. They are not a diagnosis tool, a medication
planner, or proof that one event caused another.

## Experiments compared with other LifeOS artifacts

| Artifact | Primary purpose | Typical question |
|---|---|---|
| Goal | Desired direction or outcome | “Where do I want to go?” |
| Plan | Coordinated path toward a goal | “How will I organize the work?” |
| Task | A concrete action | “What should I do next?” |
| Habit | A behavior repeated over time | “What routine do I want to maintain?” |
| Metric | A reusable observation definition | “What do I measure, and in what unit?” |
| Experiment | A bounded test of a deliberate change | “What can I learn by changing one thing and observing the result?” |

An experiment may link to all five other artifact types without replacing them.
For example, “walk after breakfast for one week” can be the intervention, a
linked habit can record whether the walk happened, and a focus metric can be the
primary outcome. The experiment owns the protocol, phases, observations,
amendments, analysis, and conclusion.

## Open the experiment workspace

Use the **Personal Experiments** ribbon icon or the command palette. Contextual
entry points may also open the workspace from goals, plans, tasks, captures,
daily or weekly reviews, experiment notes, history, and knowledge conversations.
Commands open graphical surfaces; they are not a substitute for the workspace.

The workspace supports these main views:

- **Design:** create or edit a draft protocol and inspect warnings.
- **Track:** view current phases, due observations, adherence, and stop rules.
- **Analyze:** inspect deterministic summaries and the exact observations used.
- **History:** filter experiments, inspect protocol versions, lineage, and outcomes.
- **Follow up:** preview proposals based on the result.
- **Recovery:** rebuild disposable state or inspect malformed and legacy artifacts.

## Design a small, observable experiment

Start with a question that can be answered by observations rather than memory
alone. The design workspace asks for:

1. the question and hypothesis,
2. the single change being tested,
3. what should remain unchanged,
4. a baseline or comparison condition,
5. primary, secondary, adherence, and contextual measures,
6. collection cadence and minimum useful duration,
7. expected confounders,
8. risks and stop conditions,
9. success, failure, and inconclusive criteria.

LifeOS returns separate, inspectable warnings rather than an opaque quality
score. A warning includes its code, evidence, explanation, and recommendation.
It may flag several simultaneous interventions, vague outcomes, no baseline,
short duration, sparse measurement, retrospective-only collection, unclear
adherence, duplicate experiments, or overlapping active experiments.

You may acknowledge and proceed with a reasonable but imperfect design when a
warning is not safety-blocking. Safety blocks cannot be acknowledged away.

## Lifecycle states

The normal lifecycle is:

```text
idea → drafting → baseline → scheduled → active → completed → analyzed → archived
                                ↘ paused ↗
```

An experiment may also be **abandoned** without a fabricated conclusion. Invalid
transitions fail with an explanation. A blocked experiment may remain an
informational draft but cannot enter baseline, scheduling, or active collection.

- **Idea:** the question exists, but the protocol is incomplete.
- **Drafting:** the protocol can still be edited directly.
- **Baseline:** comparison observations are being collected.
- **Scheduled:** the protocol is ready and has a future start.
- **Active:** the intervention and observations are in progress.
- **Paused:** schedules are quiet until the experiment resumes.
- **Completed:** data collection has ended.
- **Abandoned:** work stopped without pretending the evidence is complete.
- **Analyzed:** an analysis and conclusion have been recorded.
- **Archived:** the experiment remains historical evidence but is no longer active.

## Baselines, phases, and amendments

A baseline records what the selected measures look like before the intervention
or under a comparison condition. An experiment may then have one or more dated
intervention phases and an optional washout phase.

Before baseline begins, edit the draft protocol normally. After baseline or
activation, a material change must be a dated amendment. The amendment stores:

- the reason,
- a summary of changes,
- the prior protocol hash,
- the replacement protocol,
- the author and timestamp.

This preserves what was planned before results were visible. Extending duration,
changing a measure, altering the intervention, or changing success criteria is
therefore visible in the protocol history.

## Measures and missing observations

Each measure has a stable ID, display name, type, optional unit, cadence, source,
direction of improvement, valid range, missing-data behavior, aggregation rule,
and role.

Supported roles are:

- **Primary:** the main outcome used to address the question.
- **Secondary:** useful supporting outcomes.
- **Adherence:** whether the intervention or protocol was followed.
- **Contextual:** events or notes that may explain a pattern.

Quantitative observations may be counts, durations, ratings, percentages,
continuous values, or completion states. Qualitative observations may record
energy, mood, motivation, focus, difficulty, side effects, events, or explanations
for missing data.

LifeOS preserves five distinct states:

| State | Meaning |
|---|---|
| Measured | A value or qualitative observation was collected. |
| Not measured | No observation was collected. |
| Not applicable | The measure did not apply in that situation. |
| Intentionally skipped | You chose not to collect it and may record why. |
| Unavailable | Collection was impossible or the source was unavailable. |

None of the four missing states is converted to zero. Links to diary entries,
reviews, habit logs, tasks, metrics, photos, and source notes preserve provenance
without copying unrelated canonical content into the experiment.

## Schedules, due observations, and reminders

An experiment may describe daily, weekly, selected-day, or phase-relative
schedules. It may include local times, before/after anchors, flexible windows,
grace periods, and missed-observation behavior. Scheduling is timezone-safe and
pause-aware.

The artifact describes the intended schedule. LifeOS does not silently create
calendar events, reminders, notifications, habits, or tasks. Any mutation to an
external canonical artifact is a previewable proposal that must be submitted,
approved, and applied through the shared lifecycle.

## Daily and weekly review integration

Daily reviews may show experiments relevant that day, due and missed
observations, adherence prompts, optional context notes, stop-rule warnings, and
unacknowledged amendments. Weekly reviews may show active or recently completed
experiments, adherence, missing-data patterns, amendments, confounders,
descriptive trends, decisions requiring attention, and analysis readiness.

These sections are contextual and dismissible. A dismissed item remains quiet
while its evidence fingerprint is unchanged. It may return when due windows,
observations, protocol state, warnings, or analysis readiness materially change.
Choosing not to show an experiment on a review surface does not create repeated
nagging.


## Rich captures as observations

Meal, exercise, and attachment captures can be linked as contextual evidence. A
derived capture field becomes an experiment measurement only after an explicit
field-to-measure mapping and a `confirmed` or `corrected` decision. The resulting
observation preserves the capture path and hash, event time, original source
category, and decision status. Suggested or unknown values are rejected rather
than silently converted into measurements.

The schema-level experiment exclusion is enforced by the mapping helper, but the
standard Rich Capture controller does not yet expose a dedicated exclusion toggle
or a one-click mapping action. See [Rich Capture](13-rich-capture.md).

## Deterministic analysis

Analysis works locally without a language model. Depending on the measure and
data shape, LifeOS may calculate:

- observation counts,
- adherence and missing-data rates,
- baseline and intervention means, medians, and ranges,
- change from baseline,
- phase comparisons,
- simple trend descriptions,
- day-of-week patterns.

Every result lists the observation IDs used, assumptions, missing-data treatment,
limitations, and whether the method is descriptive or inferential. Direction 6
ships descriptive methods only. Raw observations remain inspectable behind each
summary and chart.

Valid conclusions include **supports the hypothesis**, **does not support the
hypothesis**, **mixed**, **inconclusive**, **protocol failure**, **insufficient
adherence**, **insufficient duration**, **too much missing data**, **confounded**,
**stopped for safety**, and **abandoned without analysis**.

A baseline difference or temporal pattern is an observed association. It does
not establish causation. LifeOS distinguishes observations, plausible
interpretations, unsupported speculation, and insufficient evidence rather than
turning a chart into a verdict.

## Visualizations and qualitative-only experiments

The workspace can derive phase timelines, observation calendars, adherence
history, baseline/intervention comparisons, metric trends, amendment markers,
and missing-data indicators. Visualizations are disposable views, not canonical
data. Raw values and uncertainty remain available.

When rendering fails, the table and textual summaries still work. Experiments
containing only qualitative observations remain usable; deterministic analysis
reports counts and evidence availability, while an optional provider may draft a
theme summary from explicitly selected excerpts.

## Safety boundaries

LifeOS blocks experiment activation or scheduling when the protocol proposes or
appears to involve medication changes, severe symptoms, dangerous physiological
targets, pregnancy-related intervention planning, eating-disorder or self-harm
risk, dangerous restriction, overtraining, sleep deprivation, substance misuse,
or illegal activity. Emergency or severe-symptom language displays an immediate
safety message and stops the workflow.

The workspace does not diagnose, recommend starting or stopping prescription
medication, treat correlations as medical evidence, or imply that an earlier
attempt proves safety. High-risk questions can be preserved as informational
planning notes that recommend appropriate professional guidance, but LifeOS will
not schedule the intervention.

## Privacy and optional providers

Creation, tracking, scheduling, deterministic analysis, reviews, history,
proposals, migration, and recovery work without a model. Optional assistance may
help clarify a hypothesis, suggest measures, identify confounders, summarize
selected qualitative observations, explain an analysis, or draft follow-up
proposals.

Before external processing, the workspace shows the selected sources, bounded
excerpts, redactions, and provider disclosure. Protected scopes are default deny.
Every preview uses `system/retrieval-policy.yml`: excluded paths never enter the
payload, and a protected path requires both an explicit grant for the current
request and a matching `external_allowed_prefixes` entry. Linked diary, health,
or other sensitive notes are not included merely because they are related. Local
analysis is the default, and telemetry avoids storing full sensitive observations.

Provider adapters use neutral capability, cancellation, timeout, malformed-output,
and no-model contracts. Model output still passes schema, safety, citation, and
proposal validation.

## From a result to an action

A completed analysis may produce a reviewed proposal to adopt or reject a
behavior, extend or repeat the experiment, create a follow-up experiment, update
a goal or plan, create or modify a habit, create tasks, write a knowledge note,
append a finding, create a research question, or add an insight to a weekly
review.

The proposal preview shows exact target paths, patches, source experiment and
hash, evidence used, limitations, included actions, excluded actions, and stale
target checks. LifeOS never silently converts a result into a permanent routine.

## History, comparison, and lineage

The history workspace filters by lifecycle state, category, goal, measure, date,
and outcome. It can open the canonical Markdown artifact, show amendments and
prior protocol hashes, compare compatible experiments, clone a protocol, and
trace repeated experiments through parent and lineage IDs.

Each repetition keeps its own identity, observations, analysis, and conclusion.
LifeOS warns rather than merging incompatible measures or protocols into a false
combined result.

## Migration and rebuilding

Canonical experiment Markdown under `experiments/YYYY/` is the source of truth.
Indexes, schedules, summaries, charts, and rebuild journals under
`.lifeos/experiments/` are disposable.

Deleting runtime state does not delete experiments. Use **Rebuild experiment
index** to recreate history and derived views. A bounded interrupted rebuild now
resumes from its prior completed source prefix when the ordered canonical
experiment paths and bytes are unchanged. Each checkpoint is source-guarded, so
editing, adding, moving, or deleting experiment Markdown before the next run
invalidates that partial progress and starts a fresh rebuild against the current
canonical source set.

A missing, truncated, corrupt, or incompatible checkpoint is disposable. LifeOS
discards it and begins a fresh rebuild instead of asking you to repair runtime
JSON or treating it as authority. Successful completion removes the checkpoint
and publishes the same sorted entries and diagnostics as an uninterrupted fresh
rebuild. Malformed artifacts, unsupported schema versions, duplicate identities,
and moved files remain diagnostics; rebuild never rewrites the source note.

Legacy migration starts with a preview. It preserves the original source, records
a stable source hash, fails closed when that source changes, resumes from an
audit trail, and avoids duplicate migration. No source file is overwritten.

## Degraded and recovery states

The workspace names degraded states and offers a specific recovery action:

- **Loading or empty:** wait for the bridge or create the first experiment.
- **No active experiment:** open history or create one.
- **Malformed artifact:** inspect the Markdown and validation error.
- **Stale artifact or conflicting edits:** reload before applying an expected-hash write.
- **Unsupported schema:** keep the Markdown and open it with a compatible version.
- **Missing index:** rebuild from canonical artifacts.
- **Rebuild in progress or interrupted:** run rebuild again to resume unchanged sources; if canonical experiment sources changed or the checkpoint is unusable, LifeOS safely restarts from current Markdown.
- **Provider unavailable or timed out:** continue locally or retry the optional action.
- **Unsafe experiment blocked:** read the user-visible safety explanation.
- **Insufficient evidence:** collect more data or conclude that evidence is insufficient.
- **Proposal stale:** recreate the preview against the current target.
- **Migration required:** preview, verify hashes, and apply conservatively.

Markdown remains readable and editable without the plugin. Recovery actions never
silently rewrite human-owned annotations.

## Keyboard and accessibility behavior

Use Tab and Shift+Tab to move among labelled controls, Enter or Space to activate
a focused action, and Escape to close transient dialogs. Focus returns to the
control that opened a dialog. Status changes are announced through screen-reader
friendly live regions and are expressed in text rather than color alone. Tables,
raw observations, warnings, and recovery messages remain available when charts
or providers are unavailable.

[← Semantic Retrieval and Knowledge Conversations](11-semantic-retrieval-and-knowledge-conversations.md) · [Manual home](README.md) · [Rich Capture →](13-rich-capture.md)
