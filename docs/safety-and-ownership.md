# Safety and Ownership

## Ownership categories

### Human-owned

Agents may read but not directly overwrite journals, user interpretations, personal profiles, important wiki claims, health conclusions, goals, or purpose statements.

### Agent-managed blocks

Agents may replace only content inside valid managed markers.

### Fully generated files

A generator may replace the whole file only when ownership is recorded in the canonical Git-tracked manifest at `system/generated-ownership.json`.

### System policy

Policy and instruction changes require explicit proposal approval.

## Minimum patch checks

- target exists
- target hash matches
- stable ID is preserved
- note type is preserved unless explicitly approved
- citations are not silently removed
- changes stay inside authorized regions
- managed markers remain valid
- source references resolve
- proposal is explicitly approved

## Personal experiment safety and ownership

Experiment protocols, observations, amendments, user annotations, conclusions,
and lineage are canonical Markdown. Managed refreshes may update only their named
blocks and require expected hashes. Runtime indexes, schedules, summaries, and
charts are disposable.

Safety policy is deterministic and user visible. LifeOS does not diagnose,
recommend prescription medication changes, encourage dangerous restriction,
deprivation, overtraining, substance misuse, self-harm, or illegal activity, or
interpret descriptive association as medical evidence. High-risk protocols are
blocked from scheduling and activation; emergency language ends the workflow with
an immediate-safety message.

Optional providers receive no linked content automatically. Protected scopes are
default deny, source selection is inspectable and bounded, and redaction may be
applied before transmission. Core experiment workflows remain local. Any result
that would change another canonical artifact becomes a proposal with exact patches,
evidence, limitations, and stale-target checks.
