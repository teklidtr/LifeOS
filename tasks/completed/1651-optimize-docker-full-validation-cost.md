---
id: LIFEOS-1651
title: Optimize Docker full-validation cost without weakening ARM64 coverage
status: completed
phase: hardening
depends_on:
  - LIFEOS-1644
risk: medium
---

# Goal

Reduce the GitHub Actions wall time and job-minutes consumed by `docker-setup-e2e` while preserving the validation guarantees introduced by LIFEOS-1644 and the later home-node ARM64 gate.

A representative LIFEOS-1649 full-validation run spent roughly four minutes in the Docker job. The dominant cost was the real `linux/arm64` image build under QEMU: the home-node Dockerfile's package-install layer alone took about 113 seconds, with additional QEMU/Buildx setup and Docker image export/load overhead. The native clean-room setup and authenticated home-node runtime gates remain valuable and are not the primary regression.

Optimize the expensive path as disposable CI performance state, never as validation authority.

# Scope

- Record the current Docker full-validation timing baseline from a representative GitHub Actions run, including QEMU setup, Buildx setup, clean-room setup/MCP gate, native home-node service gate, ARM64 build, and the dominant Dockerfile layers.
- Preserve the current full-validation lifecycle contract:
  - explicit PR `full-validation` checkpoints still run the complete Docker gate;
  - pushes to `master` and manual full-validation dispatches remain full checkpoints;
  - the Docker checkpoint still includes a real `linux/arm64` home-node image build.
- Add a bounded, disposable BuildKit/GitHub Actions layer cache for the ARM64 build when measured reuse is favorable.
  - cache misses, eviction, or cache service failure must make the build slower, never change what is validated;
  - cache state must contain only rebuildable image/build layers, never vault data, credentials, secrets, or canonical LifeOS state;
  - cache scope/keying must permit compatible reuse without making a cached result authoritative.
- Avoid unnecessary ARM64 image export/load work in CI when the build can validate the requested `linux/arm64` target without importing the image into the runner Docker daemon solely for a redundant architecture inspection.
- Restrict QEMU registration to the architecture actually required by this gate.
- Defer QEMU/Buildx setup until after native Docker gates where practical so a native integration failure does not first pay cross-architecture setup cost.
- Remove avoidable package-manager work in the home-node image while preserving runtime certificate and Git requirements. In particular, do not upgrade an already-present CA bundle merely to ensure that it exists.
- Align identical base/system-package layers between the setup and home-node Dockerfiles where safe so the second native image build can reuse work already performed in the same runner.
- Make dependency/image layering cache-friendly where the change remains small and does not alter the resulting installed application/runtime contract.
- Add project-level regression coverage for the CI contract: real ARM64 target remains present, cache is performance-only, QEMU is ARM64-scoped, and required native Docker gates remain in full validation.
- Update maintainer-facing CI documentation with the final cache behavior and measured before/after timings.

# Out of scope

- Removing the clean-room setup/MCP gate, authenticated home-node runtime gate, or ARM64 build entirely.
- Skipping the ARM64 build using a new changed-files heuristic in this task.
- Removing or weakening the full-validation trigger on `master` pushes.
- Changing branch-protection policy or required check names.
- Caching pytest results, vault data, secrets, credentials, or any canonical/runtime user state.
- Publishing a new long-lived custom base image solely to accelerate CI.
- Replacing GitHub Actions, using self-hosted runners, or buying additional Actions capacity.
- Product/runtime behavior changes unrelated to container build mechanics.

# Acceptance criteria

- `docker-setup-e2e` still exercises the clean-room setup/MCP path and the authenticated native home-node service/restart/runtime-rebuild path.
- A full checkpoint still performs a real `linux/arm64` build of `deploy/home-node/Dockerfile`.
- ARM64 cache restoration never skips the build command/action and a cache miss remains semantically equivalent to a cold build.
- Cache contents are limited to disposable BuildKit layers and are scoped so ordinary PR execution cannot make cached state authoritative or inject canonical/user data.
- QEMU installs only the required ARM64 emulator rather than all supported architectures.
- Cross-architecture setup occurs after the native Docker gates where practical.
- The home-node Dockerfile no longer performs the expensive CA-certificate package upgrade observed in the baseline solely because a newer repository package exists; the runtime still has a usable CA certificate bundle and Git.
- CI does not export/load the ARM64 image into the runner Docker daemon solely to verify the architecture that was explicitly requested by the build target.
- Project workflow tests fail if the ARM64 target or either native Docker gate is accidentally removed.
- README/maintainer documentation describes the Docker cache as disposable performance state and explains that full validation still rebuilds/validates the ARM64 target.
- At least one cold and one compatible warm full-validation run are measured. The warm ARM64 path demonstrates useful layer reuse, and the representative Docker job shows a material reduction from the approximately four-minute baseline. If hosted-runner/network variance prevents a fixed threshold, step-level evidence must show the previously dominant unchanged package/dependency layers are restored from cache rather than re-executed.
- The final material head has green `fast-checks`, required Codex review, and a green explicit `full-validation` checkpoint including `full-test` and `docker-setup-e2e`.

# Documentation impact

Status: required

- `README.md`: update the Continuous integration section to describe the ARM64 BuildKit cache, its disposable/non-authoritative semantics, and the measured Docker full-validation behavior.

# Validation

```bash
uv run pytest -q tests/project/test_ci_workflows.py
uv run pytest -q tests/project
uv run ruff check .
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
bash scripts/run-home-node-integration-docker.sh
bash scripts/validate-home-node-arm64-docker.sh
uv run pytest -q
```

Also compare GitHub Actions step/job timings for at least one cold and one compatible warm explicit full-validation run, recording cache hit/miss evidence and the observed ARM64 build-layer behavior.

# Implementation evidence

Representative hosted-runner measurements were captured on PR #26 before final review:

- Baseline full-validation run `33350329826` (before this task): `docker-setup-e2e` was about four minutes. The ARM64 package-install layer took about 112.8 seconds, QEMU/Buildx setup added roughly 24 seconds, and `--load` image export/import added roughly 13 seconds.
- First optimized full-validation run `33352350190`: the Docker job completed in about 2 minutes 23 seconds. The ARM64 package-install layer fell to about 34.5 seconds after avoiding the unnecessary CA-bundle upgrade; QEMU setup was about 5.7 seconds, Buildx about 4.3 seconds, and the ARM64 image was no longer loaded into the runner daemon. The initial GHA cache export took about 24.6 seconds. `full-test` and `docker-setup-e2e` were green and the cold fallback was not needed.
- Compatible warm full-validation run `33352571107` on the same material head: the Docker job completed in about 57 seconds. BuildKit imported the GHA cache manifest in about 0.4 seconds; the ARM64 system-package, dependency, source, project-install, runtime-directory, and workdir layers all reported `CACHED`; the cache export took about 1.5 seconds. `full-test` and `docker-setup-e2e` were green and the cold fallback was again skipped.
- The warm job therefore reduced representative Docker checkpoint wall time by more than 75% from the approximately four-minute baseline without removing a validation gate. The measurements are regression evidence rather than a hosted-runner SLA.
- After these measurements, cache import/export was explicitly bounded to one minute. A cache-backed build failure still falls back to a real `no-cache` ARM64 build, while cache export is best-effort, so cache availability cannot become validation authority.

# Relevant decisions

- LIFEOS-1644: fast PR checks and explicit full validation are separate; caches are disposable performance state and must never weaken validation. Docker layer caching was previously rejected when the Docker build cost was only about 11.5 seconds, so the decision must be revisited using the new ARM64 cost profile rather than retained mechanically.
- DD-033: disposable derived/query state is rebuildable rather than authoritative; CI caches follow the same rebuildable-state posture.
- DD-036: Python remains the sole business-rule engine; CI optimization must not bypass deterministic product validation.
- `AGENTS.md` Pull Request Review Workflow: the final material head still requires green fast checks, review, and an explicit full-validation checkpoint before merge readiness.
