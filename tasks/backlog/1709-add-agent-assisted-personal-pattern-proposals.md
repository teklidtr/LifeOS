---
id: LIFEOS-1709
title: Add evidence-bounded agent-assisted personal-pattern proposals
status: backlog
phase: 17
depends_on:
  - LIFEOS-1703
  - LIFEOS-1705
  - LIFEOS-1707
risk: high
---

# Goal

Allow an external agent to propose semantically richer personal hypotheses from explicitly bounded evidence without granting the agent authority to define the user.

# Scope

- Add bounded MCP/facade operations for proposing a new pattern and reviewing an existing one.
- Require exact selected canonical evidence references and observed hashes.
- Accept a concise hypothesis, rationale, supporting evidence, contesting evidence, competing explanations, limitations, and proposed confidence class.
- Independently verify selected sources before publishing a draft.
- Reuse normal pattern proposal builders and proposal persistence.
- Stop at draft and allow a zero-proposal outcome.
- Preserve provider-neutral contracts.

# Out of scope

- Autonomous vault-wide psychological profiling.
- Hidden model reasoning storage.
- Automatic promotion to active.
- Agent-selected approval identity.
- Provider-specific canonical fields.
- Diagnoses or clinical personality conclusions.

# Required invariants

- The agent may propose an interpretation, never establish it.
- Every durable claim is tied to supplied evidence.
- Competing explanations remain inspectable.
- LifeOS verifies source versions independently.
- Protected scopes remain governed by existing policy.
- No hidden chain-of-thought is stored.

# Acceptance criteria

- Semantic personal hypotheses can enter LifeOS only as evidence-backed draft proposals.
- MCP cannot directly mutate `patterns/`.
- Local deterministic operation remains possible without a model provider.
- Tests cover valid proposals, zero-change, changed/missing/protected sources, counter-evidence, existing-pattern review, malformed model output, timeout, and network lifecycle restrictions.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document the agent boundary.
- `docs/user-manual/15-mcp-exploration.md`: document personal-pattern proposal flow.
- `docs/user-manual/`: explain evidence-bounded agent assistance.
- `docs/design-decisions.md`: record the proposal-only semantic interpretation boundary.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-002
- DD-003
- DD-010
- DD-016
- DD-062
- DD-066
- DD-087
- DD-091
