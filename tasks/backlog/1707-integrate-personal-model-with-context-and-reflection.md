---
id: LIFEOS-1707
title: Integrate Personal Model with context and reflection
status: backlog
phase: 17
depends_on:
  - LIFEOS-1705
risk: high
---

# Goal

Allow accepted personal hypotheses to inform reflection and agent context while preserving the distinction between evidence and instruction.

# Scope

- Expose bounded Personal Model context through the typed Python facade.
- Allow relevant canonical pattern notes to contribute to Context Packs, knowledge conversations, goal-to-plan clarification, experiment design context, and review explanations.
- Distinguish active, seed, needs-review, and archived hypotheses.
- Include status, evidence state, and canonical references in context.
- Respect protected-scope, redaction, disclosure, and provider boundaries.
- Treat pattern content as evidence, never runtime instruction authority.

# Out of scope

- Planner score or selection changes.
- Automatically turning a pattern into a planning rule.
- Sending the entire Personal Model to every provider request.
- Hidden personality prompts.

# Required invariants

- Context inclusion is bounded and question-relevant.
- `system/instructions.yml` remains the only vault-specific routed instruction authority.
- Patterns cannot authorize mutation.
- Needs-review patterns remain visibly uncertain.
- Provider disclosure remains inspectable.

# Acceptance criteria

- Agents can reason with reviewed personal evidence without receiving an opaque universal profile.
- Context remains traceable to canonical pattern artifacts.
- Planner output is unchanged by this task.
- Tests cover relevance bounds, needs-review labeling, protected content, redaction, no-provider behavior, and instruction-injection resistance.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document the context contract.
- `docs/architecture.md`: document Context Pack integration.
- `docs/user-manual/11-semantic-retrieval-and-knowledge-conversations.md`: document personal-pattern evidence.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-010
- DD-014
- DD-016
- DD-048
- DD-060
- DD-062
- DD-063
- DD-087
