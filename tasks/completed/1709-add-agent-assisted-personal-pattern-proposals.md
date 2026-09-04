---
id: LIFEOS-1709
title: Add evidence-bounded agent-assisted personal-pattern proposals
status: completed
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

Local execution note: this implementation session has repository write/read access through the
GitHub connector but no working local checkout because direct GitHub DNS/network access from the
execution container is unavailable. Repository-wide dependency/seam search and branch diff audit
were therefore used as the pre-push static substitute required by `AGENTS.md`; deterministic
validation was delegated explicitly to the PR checkpoints rather than being represented as locally
executed.

Completion validation:

- PR #49 `fast-checks` run `33911365460` passed on implementation head
  `2c826ef6b5865daf09f7a25ebb362bad7f96a368`, including documentation impact, manual links,
  Ruff, strict mypy, compile, test collection, and contract smoke tests.
- PR #49 final `full-validation` run `33911420447` passed on the same implementation head:
  all four pytest shards and aggregate `full-test` succeeded, and `docker-setup-e2e` succeeded for
  clean-room setup/MCP, home-node service, and ARM64 image build.
- All actionable normal Codex review threads were addressed and resolved. Repeated variants of the
  retrieval-policy privacy invariant were closed by a sibling-boundary audit and centralized
  current-policy enforcement rather than another iterative review loop, per `AGENTS.md`.
- The otherwise applicable Codex security review was intentionally skipped under the user's
  explicit instruction for this task.

# Relevant design decisions

- DD-002
- DD-003
- DD-010
- DD-016
- DD-062
- DD-066
- DD-087
- DD-091
- DD-100
