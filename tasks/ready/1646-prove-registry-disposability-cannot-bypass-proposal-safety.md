---
id: LIFEOS-1646
title: Prove registry disposability cannot bypass proposal safety
status: ready
phase: 16
depends_on:
  - LIFEOS-1638
  - LIFEOS-1643
risk: high
---

# Goal

Add explicit security-invariant regression coverage proving that deleting, recreating, or
refreshing the disposable SQLite registry cannot turn a consequential proposal that should be
refused into one that can be accepted or applied.

The registry is derived query/index state. Canonical Markdown, proposal artifacts, review
digests, target hashes, and `system/generated-ownership.json` remain authoritative. A missing or
freshly rebuilt `.lifeos/registry.db` must therefore never erase a stale-target conflict, generated
ownership conflict, lifecycle restriction, or reviewed-content binding.

The invariant is:

> Removing or rebuilding disposable registry state must not increase canonical mutation authority.

Equivalently, if proposal application is invalid before registry deletion for an authoritative
reason, it must remain invalid after registry deletion/reinitialization unless the authoritative
canonical state itself is deliberately changed through its supported workflow.

# Scope

- Add regression tests around the shared proposal/application boundary, not only registry helper
  behavior.
- Exercise both relevant disposable-state conditions where practical:
  - `registry.db` is absent after deletion;
  - `registry.db` is recreated/refreshed from canonical vault state before the proposal is retried.
- Prove stale-target safety for a human-owned target:
  1. create and approve a proposal bound to target hash `H1`;
  2. mutate the canonical target to `H2` outside that proposal;
  3. verify application is refused as stale/conflicting;
  4. delete the SQLite registry;
  5. optionally rebuild it through the supported registry refresh path;
  6. retry the same authoritative proposal state;
  7. verify application is still refused and the `H2` target remains byte-for-byte unchanged.
- Prove durable generated-ownership safety:
  1. create a generated-owned canonical target and matching
     `system/generated-ownership.json` entry;
  2. establish a proposal whose generated replacement would normally require that ownership and
     expected content state;
  3. create an authoritative ownership/application conflict, such as externally modifying the
     target so its current hash no longer matches the canonical ownership manifest;
  4. verify application is refused;
  5. delete and, in a separate case when useful, rebuild the registry;
  6. verify the same proposal remains refused and neither the target nor ownership manifest is
     silently rewritten.
- Prove proposal lifecycle/history does not reset through registry deletion:
  - an already applied/rejected/otherwise terminal proposal must not become a fresh draft or
    otherwise gain a new legal mutation path because the proposal index disappeared;
  - after registry rebuild, indexed status must be derived from canonical proposal artifacts rather
    than used to overwrite them.
- Add review-binding coverage if the existing suite does not already prove the same disposability
  invariant: tampering with or invalidating the authoritative reviewed proposal artifacts must not
  become acceptable merely because registry state is deleted/rebuilt.
- Exercise the user-facing consequential facade path (`accept` and/or `apply`, according to the
  proposal state under test) in addition to lower-level application coverage when this is necessary
  to prove that no adapter/facade path treats SQLite as mutation authority.
- Assert negative side effects on every refusal path:
  - no unintended canonical target write;
  - no unintended ownership-manifest write;
  - no false `APPLIED` lifecycle transition;
  - no registry-derived fact is promoted into authority to repair or override canonical state.
- If any new regression test currently fails, fix the invariant at the smallest shared authoritative
  validation/application boundary. Do **not** fix the test by making SQLite authoritative or by
  copying canonical authorization state into the registry as the new source of truth.
- Prefer parametrized/shared fixtures for `registry present`, `registry deleted`, and `registry
  rebuilt` variants so the test suite demonstrates that the authoritative outcome is invariant to
  disposable-registry state without duplicating large scenario setup.

# Out of scope

- Changing the canonical ownership format or moving ownership into SQLite.
- Changing proposal lifecycle semantics merely to make the tests easier.
- Adding new proposal operations or ingestion behavior.
- Reworking registry scan/refresh performance, filesystem watching, or incremental scan design.
- Making the registry a required dependency of proposal application when application can validate
  authoritative state directly.
- Broad recovery-system redesign unrelated to a registry-deletion bypass found by these tests.
- Fixing unrelated registry documentation/schema-version drift unless it directly blocks accurate
  documentation of this invariant; record unrelated drift as separate backlog work.

# Acceptance criteria

- [ ] A stale human-target proposal is refused before registry deletion and remains refused after
      registry deletion, with the current canonical target unchanged.
- [ ] The stale human-target case is also covered after supported registry initialization/refresh,
      proving rebuild does not grant additional mutation authority.
- [ ] A generated-target ownership/hash conflict is refused before registry deletion and remains
      refused after deletion/rebuild, with both target bytes and canonical ownership manifest
      unchanged.
- [ ] At least one canonical proposal lifecycle/history case proves registry deletion/rebuild cannot
      reset proposal state or enable duplicate/otherwise illegal application.
- [ ] Where the public/user-facing facade has a distinct acceptance path, regression coverage proves
      that path preserves the same invariant rather than relying only on a lower-level unit test.
- [ ] Failed attempts do not persist a false applied state, rewrite canonical targets, or repair
      ownership from disposable registry facts.
- [ ] Tests explicitly demonstrate that canonical proposal artifacts, reviewed hashes/digests,
      current target state, and canonical generated ownership remain authoritative after registry
      loss.
- [ ] Any production fix required by a failing regression is centralized at the shared validation or
      application boundary and does not make registry state authoritative.
- [ ] Existing registry refresh/rebuild behavior remains compatible and the full test suite passes.

# Documentation impact

Status: required

- `docs/registry.md`: state the security invariant that deleting/reinitializing/rebuilding the
  disposable registry cannot increase proposal/application authority, reset canonical proposal
  lifecycle state, erase stale-target protection, or erase canonical generated ownership.

No new design decision is expected if implementation confirms the existing contract in DD-033,
DD-034, and DD-035. If the implementation reveals that the durable authority model must change,
stop and record that as an explicit design-decision change rather than silently expanding this
regression task.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/registry tests/proposals tests/facade tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
```

# Relevant decisions

- DD-001: Markdown remains canonical.
- DD-002: Deterministic facts and semantic interpretation are separate.
- DD-004: Proposal application is explicit.
- DD-033: SQLite is disposable and rebuildable; proposal history is not owned by SQLite.
- DD-034: Approval does not bypass application-time validation; changed targets are refused as
  stale.
- DD-035: Generated ownership is durable canonical authorization data in
  `system/generated-ownership.json`; deleting SQLite must not affect ownership.
- DD-038: Existing canonical writes use optimistic concurrency and stale writes fail closed.
