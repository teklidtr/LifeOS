[← Previous: System Architecture](01-system-architecture.md) · [Manual home](README.md) · [Next: Feature Breakdown →](03-feature-breakdown.md)

# 2. Executive Summary & Philosophy

LifeOS is a private, local-first system for managing knowledge, study, plans,
journals, personal observations, and AI-assisted changes inside an
Obsidian-compatible Markdown vault.

Its central principle is:

> **Markdown is the truth. Everything else is an index, interpretation,
> proposal, or disposable view.**

LifeOS is not designed to squeeze every minute into a productivity spreadsheet.
It is designed to help you understand:

- what you are trying to accomplish;
- which actions fit your current energy and motivation;
- which study material needs attention;
- what patterns may exist in your habits and personal metrics;
- where an idea came from;
- what an AI agent wants to change before you authorize it.

## Productivity philosophy

### Getting Things Done

LifeOS follows the useful parts of the GTD loop:

1. **Capture** thoughts quickly.
2. **Clarify** whether they are knowledge, actions, projects, observations, or
   reference material.
3. **Organize** them into canonical vault areas.
4. **Review** plans and incomplete material regularly.
5. **Engage** using a realistic menu of actions.

The main difference is that tasks stay close to their plans instead of being
poured into one giant global list.

### PARA

LifeOS is not a literal PARA implementation, but its domains map naturally to
the same mental model:

| PARA concept | LifeOS equivalent |
| --- | --- |
| Projects | `plans/` |
| Areas | `goals/`, `profile/`, recurring reviews |
| Resources | `wiki/`, `study/`, `raw/` |
| Archives | `status: archived` or an archive structure you define |

### Atomic Habits

LifeOS treats behavior as a feedback loop rather than a moral scorecard. You may
record:

- activities;
- energy;
- motivation;
- environmental conditions;
- health or lifestyle metrics;
- completed, avoided, or blocked actions.

The observation layer may surface candidate associations, but it does not
present correlations as causes. The goal is to improve your environment and
planning assumptions, not to build a tiny surveillance department in your
notebook.

## Human-in-the-loop AI

AI may:

- analyze a source;
- suggest a wiki page;
- generate a proposal;
- identify possible relationships;
- help decompose a goal;
- create candidate flashcards or explanations.

AI may not silently rewrite important canonical material. Submission, approval,
and application are separate lifecycle steps. Consequential tools use a trusted
authorizer, and agent-controlled input cannot manufacture approval identity or
bypass validation.

## Rolling-wave planning

LifeOS keeps different time horizons at different levels of detail:

```text
long-term direction
  ↓
medium-term outcome
  ↓
near-term actions
  ↓
daily menu matched to current capacity
  ↓
result and observation
  ↓
plan improves
```

Long-term goals remain broad. Medium-term plans define outcomes. Only the next
one or two weeks need detailed actions. This reduces brittle planning and keeps
the system useful when energy, interests, or circumstances change.

## What LifeOS deliberately avoids

LifeOS is not:

- a corporate productivity dashboard;
- an obligation factory that turns every interest into work;
- a fully autonomous agent that rewrites the vault;
- a giant universal ontology;
- a replacement for Obsidian;
- a second canonical database of personal knowledge;
- a system that presents personal correlations as medical or causal facts.

---

[← Previous: System Architecture](01-system-architecture.md) · [Manual home](README.md) · [Next: Feature Breakdown →](03-feature-breakdown.md)
