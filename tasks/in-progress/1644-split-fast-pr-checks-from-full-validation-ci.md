---
id: LIFEOS-1644
title: Split fast PR checks from full validation CI and add measured caching
status: in-progress
phase: 16
depends_on:
  - LIFEOS-1639
risk: low
---

# Goal

Reduce GitHub Actions minutes and PR feedback latency without weakening LifeOS validation.

The current CI workflow runs the full repository test suite and clean-room Docker setup gate on
every pull-request synchronization, including review-fix and documentation-only pushes. During
LIFEOS-1639 this caused repeated full CI runs even when the next change was small and mechanical.

Split CI into a fast PR-feedback path and an explicit/full validation path, then use GitHub
Actions cache storage only where measured warm-cache savings exceed restore/save overhead and
cache churn.

The result should preserve the repository's existing safety standard: cheap checks run quickly
and often; expensive validation still runs at meaningful checkpoints and before merge when the
change requires it.

# Design principles

- CI optimization must not weaken correctness, privacy, mutation-boundary, or integration
  validation.
- Prefer deterministic workflow structure over agent memory or informal convention.
- Keep fast checks frequent and full checks intentional.
- Treat cache as disposable performance state, never as an authority or correctness input.
- A cache miss, cache eviction, or unavailable cache must only make CI slower, never change the
  validation result.
- Measure cold and warm runs before retaining a new cache. Do not cache a tool merely because it
  supports caching.
- Keep cache keys narrow enough for correctness but broad enough to reuse unchanged work across
  commits in the same PR and from a compatible default-branch baseline.
- Avoid cache-key designs that include the complete source-tree hash in the only restore key,
  because that prevents useful incremental reuse after every code change.
- Keep cache storage bounded and avoid cache thrashing. Prefer a few high-value caches over many
  large per-commit caches.
- Do not rely on `.pytest_cache` as a test-result cache; normal pytest cache state does not make
  the full suite safely skippable.

# Current state

- `.github/workflows/ci.yml` currently runs on every pull request targeting `master`, on pushes to
  `master`, and through manual dispatch.
- The `test` job currently runs documentation impact validation, Ruff, mypy, compileall, manual
  link validation, pytest collection, and the full pytest suite.
- `docker-setup-e2e` currently runs the clean-room setup/MCP Docker gate in parallel on every PR
  synchronization.
- `astral-sh/setup-uv` already has `enable-cache: true`; dependency caching must be preserved and
  evaluated rather than duplicated with a second uv cache.
- Mypy already produces an incremental `.mypy_cache` locally, but fresh GitHub-hosted runners do
  not retain it unless Actions cache storage restores it.
- Ruff uses `.ruff_cache`, but Ruff is expected to be fast enough that cache restore/save overhead
  may outweigh the benefit; retain this cache only if measurement demonstrates a net win.

# Scope

- Measure a representative current CI baseline, including at minimum:
  - dependency setup / `uv sync`;
  - Ruff;
  - mypy;
  - pytest collection;
  - full pytest;
  - clean-room Docker setup/MCP gate;
  - total workflow wall time and approximate Actions job-minutes.
- Split CI so routine PR synchronization gets a fast feedback path containing the inexpensive,
  high-signal checks needed on every push.
- Define a full-validation checkpoint that runs the complete required repository validation,
  including full pytest and the clean-room Docker gate.
- Ensure the full checkpoint can be intentionally requested after material review fixes and is
  automatically run at appropriate lifecycle boundaries such as the default branch and/or an
  equivalent merge checkpoint.
- Choose a checkpoint trigger that is practical for the repository's agent-driven GitHub
  workflow. Prefer a mechanism that can be invoked deterministically through normal GitHub
  operations, such as a dedicated label/event or another explicit supported trigger, rather
  than relying on a human remembering a hidden convention.
- Preserve `concurrency` cancellation so superseded PR runs do not continue consuming minutes.
- Evaluate whether documentation-only changes can avoid Python/Docker work while still running
  the documentation-impact contract needed for those changes.
- Preserve the existing `setup-uv` cache and verify that its key/invalidation behavior is useful
  for this repository.
- Add and benchmark an Actions cache for `.mypy_cache`:
  - invalidate on incompatible runner/Python/mypy/dependency/configuration changes;
  - permit restore from the most recent compatible cache so unchanged modules can be reused;
  - allow mypy itself to invalidate changed modules deterministically;
  - never use cache presence to skip the mypy command.
- Benchmark `.ruff_cache` through Actions cache storage. Keep it only if warm-cache savings exceed
  cache restore/save overhead by a meaningful margin on representative PR runs.
- Do not add `.pytest_cache` as a general test-result optimization. If future pytest acceleration
  is considered, it must use a correctness-preserving mechanism with an explicit task/decision.
- Evaluate Docker layer caching separately because the clean-room Docker build may be a larger
  cache opportunity than Ruff:
  - prefer BuildKit/GitHub Actions cache integration or another bounded layer-cache mechanism;
  - preserve the semantic meaning of a clean-room setup test;
  - retain it only if measured storage and time tradeoffs are favorable.
- Record cache hit/miss visibility in Actions output so a slow run can be diagnosed without
  guessing whether cache reuse occurred.
- Keep cache contents limited to rebuildable tool/dependency/build state. Never cache vault data,
  secrets, credentials, proposal state, or other user/canonical LifeOS content.
- Account for GitHub cache scope and trust rules so untrusted or lower-trust PR execution cannot
  turn cache restoration into a privileged data or code path.
- Document the final CI/checkpoint behavior where maintainers and coding agents will see it.

# Out of scope

- Removing full pytest or the clean-room Docker setup/MCP validation entirely.
- Skipping tests based on an unproven changed-files heuristic.
- Making cached output authoritative for whether a check passes.
- Replacing GitHub Actions with another CI provider.
- Self-hosted runners.
- Increasing paid Actions/cache quotas as the primary optimization.
- General test-suite refactoring unrelated to CI orchestration.
- Adding distributed test execution infrastructure.

# Acceptance criteria

- Routine PR synchronize events no longer run the complete expensive validation stack by default
  when a cheaper feedback path is sufficient.
- The fast PR path still catches formatting/lint, type, compile/import/contract, documentation,
  and other selected high-signal failures appropriate for every push.
- A deterministic full-validation checkpoint exists and runs the complete required suite before
  a PR is treated as merge-ready under the repository workflow.
- Pushes to `master` retain full validation or an equivalently strong post-merge gate.
- Material review fixes can request another full checkpoint without requiring dummy source
  commits.
- Superseded workflow runs are cancelled rather than consuming unnecessary minutes.
- Existing uv dependency caching remains enabled and is not redundantly duplicated.
- `.mypy_cache` is restored/saved with a correctness-safe key strategy and a warm representative
  run demonstrates a measurable net reduction in mypy wall time versus the cold baseline.
- `.ruff_cache` is retained only if measured warm-cache savings are larger than cache
  restore/save overhead; otherwise the task explicitly records that Ruff caching was tested and
  intentionally omitted.
- Docker layer caching is measured and either implemented with bounded storage or explicitly
  rejected with the measured reason.
- Cache miss/eviction leaves every validation command runnable and semantically identical to a
  cold run.
- Cache entries contain no canonical LifeOS/user data, secrets, credentials, or privileged
  runtime state.
- Cache keys invalidate on relevant toolchain/dependency/config changes and support useful
  incremental restoration across compatible commits rather than forcing a cold cache on every
  source edit.
- The implementation records before/after measurements for at least one cold and one warm
  representative run, including cache sizes where available.
- The final workflow avoids pathological cache churn relative to the repository-configured
  Actions cache storage limit.
- Branch protection / required-check expectations remain coherent after workflow/check names are
  split or renamed.
- A representative implementation PR demonstrates:
  - fast checks on an ordinary synchronize event;
  - an intentional full-validation checkpoint;
  - a warm mypy cache hit on a subsequent compatible run;
  - full validation still fails when a deliberately failing regression is introduced in a test
    fixture or temporary validation experiment.

# Documentation impact

Status: required

- `AGENTS.md`: update the pull-request workflow only if the command/label/checkpoint used by
  coding agents to request final full validation needs to be explicit there.
- `README.md` or the most appropriate contributor/operations documentation: document the fast
  versus full CI contract, required checks, and how to request a full checkpoint when needed.

# Validation

```bash
uv run ruff check .
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
uv run pytest --collect-only -q
uv run pytest -q
./scripts/run-setup-integration-docker.sh
```

In addition to command correctness, compare GitHub Actions step/job timings for representative
cold-cache and warm-cache runs and record the observed cache sizes/hit status in the task or PR.

# Implementation evidence

## Baseline and fast path

Representative pre-change CI measured approximately 68 seconds on the critical `test` job:
`uv sync` ~2.25s with a setup-uv cache hit, Ruff ~0.09s, mypy ~7.4s without a persisted
incremental cache, pytest collection ~4.6s wall, full pytest ~48.2s wall, and the clean-room
Docker command ~36.1s in its parallel job.

The split PR path measured ~22s with a cold/missing mypy Actions cache and ~16.4s on a compatible
warm run. The warm `.mypy_cache` was ~1.85 MB compressed / ~15 MB unpacked; cache restore plus
mypy was ~1.73s versus ~5.0s for cold mypy. Ruff remained around 0.1s, so persisting
`.ruff_cache` was rejected because Actions restore/save overhead would dominate the work.

Persistent Docker layer caching was also rejected for this iteration. Once Docker was removed
from ordinary PR synchronizations, a representative explicit checkpoint spent ~11.5s in
build/export. Adding a persisted layer cache would introduce transfer/storage/maintenance cost
for an infrequent gate while leaving the clean-room runtime validation unchanged.

## Pytest acceleration

A disposable benchmark PR compared serial pytest, pytest-xdist, pytest-testmon, and four-way
pytest-split sharding. Xdist showed large hosted-runner variance and testmon instrumentation was
slower than the uninstrumented full suite even on warm affected-test runs. Four stateless
pytest-split shards were therefore selected: every checkpoint still executes every test, and no
pytest result cache, affected-test cache, or duration-history cache can affect selection.

The largest original pytest bottleneck was
`test_weekly_history_is_bounded_and_fast_for_a_long_vault`. Its ~13s runtime came from fixture
setup creating 120 review artifacts through `open_or_create()`, repeatedly exercising the
production duplicate-ID scan and making setup effectively O(n^2). The test now directly seeds
the same 120 valid canonical artifacts, while the production history/load/metadata-validation
path and duplicate-ID safety remain unchanged. The test measured ~0.17s afterward.

A second combined experiment-rebuild test was split by behavior so only the interruption/large
history scenario retains a 105-artifact vault. Runtime deletion, rename, and duplicate-identity
checks now use small isolated vaults. The large scenario measured ~1.95s instead of the earlier
combined test's ~4.92s while failure localization improved. The complete suite grew from 1570 to
1573 tests because one combined scenario became four focused tests.

A representative post-refactor full checkpoint executed all 1573 tests across four stateless
shards: 394/393/393/393 tests, with test phases of ~10.90s, ~18.94s, ~11.47s, and ~14.27s. The
slower second shard contained several 1-2s recovery/integration tests rather than a single
pathological test, so no correctness-affecting selection cache was introduced to chase hosted
runner variance.

## Safety experiments

A temporary test containing an intentional `assert False` was committed to the implementation
PR. Ordinary `fast-checks` remained green because the fast path successfully collected the
complete suite but did not execute the full suite. Explicit full validation run `32759864216`
then failed exactly on that probe in `full-test-shard-1`, and the aggregate `full-test` gate
failed. The probe was removed immediately afterward, and the fixed head returned to green fast
and full validation.

Supersession was also tested with a temporary full-only sleep probe. Fast checks collected the
probe without executing it. Full validation run `32760355439` was started on that head; while
its pytest shards were running, the probe was removed in a newer commit. The shared
`lifeos-pr-11` concurrency group cancelled the stale run rather than allowing obsolete work to
continue. No temporary probe remains in the branch.

# Relevant decisions

- LIFEOS-1639: repeated review-fix pushes demonstrated that full pytest plus Docker on every PR
  synchronization consumes unnecessary Actions minutes while the final full gates remain useful.
- `AGENTS.md` Pull Request Review Workflow: material review fixes may require another review and
  validation cycle; CI should support that workflow without making every intermediate push a full
  checkpoint.
- DD-033: disposable runtime state is rebuildable; CI caches follow the same disposable-state
  principle and must never become authoritative.
- DD-036: deterministic Python owns business-rule enforcement; CI optimization must not bypass
  those deterministic validations.
