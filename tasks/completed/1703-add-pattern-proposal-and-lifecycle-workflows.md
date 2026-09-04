---
id: LIFEOS-1703
title: Add proposal-gated personal-pattern lifecycle
status: completed
phase: 17
depends_on:
  - LIFEOS-1701
  - LIFEOS-1702
risk: high
---

# Goal

Allow users and deterministic LifeOS workflows to track, adopt, revise, contest, and archive personal hypotheses without bypassing the proposal boundary.

# Scope

- Add typed pattern proposal builders for creating a seed, promoting seed to active, revising statement/evidence, marking needs-review, resolving review, and archiving.
- Reuse existing `create_file` for new human-owned pattern files and `patch_human_file` for existing patterns.
- Bind existing-target changes to current content hashes.
- Include evidence fingerprints and transition reasons in proposal metadata.
- Reuse existing proposal review snapshots, approval, application, stale-write, authorization, and recovery semantics.

# Out of scope

- Automatic approval.
- Automatic promotion from observation to active.
- Direct file writes from agents.
- Generated ownership for personal interpretations.

# Required invariants

- Detecting a candidate creates no canonical pattern.
- Creating a seed means track this hypothesis, not accept it as true.
- Activating a pattern requires explicit review.
- A stale target blocks application.
- Agents cannot select the approving identity.

# Acceptance criteria

- Every consequential pattern transition is proposal-gated.
- Newly created pattern files are human-owned canonical files.
- Existing proposal authorization and recovery semantics apply unchanged.
- Tests cover create, promote, revise with counter-evidence, stale target, rejection, recovery, archive, and target collision.

# Documentation impact

Status: required

- `docs/personal-model-architecture.md`: document lifecycle.
- `docs/user-manual/`: explain tracking versus adopting a hypothesis.
- `docs/design-decisions.md`: record any new durable lifecycle choice.

# Validation commands

- `pytest -q`
- `ruff check src tests`
- `mypy src`
- `git diff --check`

# Relevant design decisions

- DD-003
- DD-004
- DD-011
- DD-012
- DD-031
- DD-032
- DD-034
- DD-038
- DD-083
