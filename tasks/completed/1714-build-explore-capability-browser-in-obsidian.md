---
id: LIFEOS-1714
title: Build Explore capability browser in Obsidian
status: completed
phase: 17
depends_on:
  - LIFEOS-1712
  - LIFEOS-1713
risk: medium
---

# Goal

Give users an Obsidian-native Explore surface that answers “What can LifeOS actually do?” from the authoritative semantic capability registry, with enough explanation and examples to discover features without turning Explore into a generic prompt library.

# Scope

- Add a dedicated LifeOS Explore workspace view in the Obsidian plugin.
- Add a `LifeOS: Open Explore` command that opens/focuses that view.
- Load capability data through the Python desktop bridge API from LIFEOS-1712; do not duplicate the catalog in TypeScript.
- Render only capabilities whose registry visibility is `explore`.
- Provide a searchable/browsable catalog with:
  - human-facing category grouping;
  - capability name and concise description;
  - maturity/status indication when present;
  - static setup requirements/prerequisites when present;
  - an obvious way to open capability details.
- Provide a capability detail presentation that can show:
  - fuller description and category/status metadata;
  - relevant requirements/prerequisites;
  - existing direct entry point(s), when declared by the registry;
  - optional example prompts.
- Treat example prompts as teaching aids. Provide a copy action for them; do not auto-submit a prompt or imply that free-form model reasoning is a LifeOS implementation.
- When a capability declares an existing direct entry point, route the action through the plugin's existing command/view/workflow mechanism rather than creating a parallel execution stack.
- Add appropriate loading, empty, bridge-unavailable, malformed-response, and retry/reconnect states consistent with the current desktop plugin architecture.
- Keep search/filter behavior deterministic and local to the returned registry payload.
- Add plugin tests for catalog rendering, visibility filtering, search/category behavior, capability details, prompt-copy behavior, direct entry-point dispatch, and failure states.

# Out of scope

- A third-party plugin marketplace, installation flow, package management, ratings, reviews, or remote capability downloads.
- Personalized recommendations, “new since last visit,” usage analytics, ranking, or behavioral targeting.
- A generic prompt marketplace or catalog of things any LLM can answer without LifeOS.
- Implementing capabilities that are missing from the backend inventory.
- Reimplementing Python-owned capability metadata or feature logic in TypeScript.
- Automatically executing example prompts.

# Required invariants

- Explore is a view over the Python-owned semantic capability registry, not a second source of truth.
- The plugin remains a thin UI over Python-owned behavior.
- A capability is shown because LifeOS implements backing machinery/workflows/data access, not because a plausible prompt can be written for it.
- Internal capabilities and low-level protocol methods are not leaked into Explore merely because they exist in `system.handshake`.
- Explore never mutates canonical Markdown simply by browsing, searching, or opening capability details.
- Existing capability entry points retain their current authorization, privacy, proposal, and mutation boundaries.

# Acceptance criteria

- `LifeOS: Open Explore` opens a dedicated Explore view in Obsidian.
- The view renders the current backend registry without a hard-coded TypeScript feature list.
- Users can search and browse capabilities by human-facing category and open a capability detail presentation.
- Internal registry entries are not displayed.
- Status/requirements and optional example prompts are rendered when present and omitted cleanly when absent.
- Example prompts can be copied but are not automatically run.
- Declared direct entry points invoke the existing LifeOS UI/workflow destination rather than bypassing its normal boundary.
- Bridge-unavailable and malformed/empty registry responses produce clear recoverable UI states rather than a blank or misleading catalog.
- Plugin tests cover the principal discovery and failure paths.

# Documentation impact

Status: required

- `docs/user-manual/06-obsidian-desktop.md`: document how to open and use Explore, what capability cards mean, and how example prompts differ from implemented LifeOS capability backing.
- `docs/user-manual/03-feature-breakdown.md`: point users to Explore as the live discoverability surface for implemented capabilities.
- `docs/obsidian-desktop-architecture.md`: document the Explore view as a consumer of the Python-owned capability registry and its thin-client boundary.

# Validation commands

- `npm --prefix packages/obsidian-plugin ci`
- `npm --prefix packages/obsidian-plugin run lint`
- `npm --prefix packages/obsidian-plugin run typecheck`
- `npm --prefix packages/obsidian-plugin test`
- `npm --prefix packages/obsidian-plugin run build`
- `pytest -q`
- `git diff --check`

# Relevant design decisions

- DD-037
- DD-101

# Implementation record

- Added the dockable `lifeos-explore` Obsidian view and `LifeOS: Open Explore` command as a thin client over the Python-owned `capability.list` registry from LIFEOS-1712/LIFEOS-1713; no TypeScript capability catalog was introduced.
- Added runtime validation for the semantic capability payload, default filtering of `visibility != explore`, deterministic local search/category grouping, capability details, requirements/status rendering, copy-only example prompts, and explicit loading/empty/malformed/bridge-unavailable/retry states.
- Routed only registry-declared `obsidian_command` and `obsidian_view` entry points through the plugin's existing execution/open-view boundaries. CLI, MCP, workflow, and data-source entry points remain descriptive references rather than parallel execution paths.
- Audited every Explore-visible Obsidian command/view target in the current semantic registry against the plugin registrations. Review exposed that registry command IDs are plugin-local while Obsidian dispatch expects the global `lifeos:` command namespace; the adapter now performs that translation and regression coverage verifies the registered command ID.
- Preserved search usability across synchronous rerenders by restoring focus/selection, then hardened the same boundary for IME composition so composed input is not replaced mid-session and filtering applies after `compositionend`.
- Added plugin regression coverage for visibility filtering, grouping/search/category behavior without extra bridge reads, details/requirements, prompt copy-only behavior, declared entry-point dispatch and arbitrary-command rejection, empty/malformed/unavailable states, reconnect success/failure, command namespacing, search focus/caret preservation, and IME composition behavior.
- Updated `docs/obsidian-desktop-architecture.md`, `docs/user-manual/03-feature-breakdown.md`, and `docs/user-manual/06-obsidian-desktop.md` to make Explore the live discoverability surface while preserving the Python-owned registry boundary and the distinction between implemented entry points and teaching prompts.
- A fresh local checkout could not be obtained in the tool container because GitHub DNS resolution failed (`Could not resolve host: github.com`). Per `AGENTS.md`, unavailable local execution was recorded rather than silently skipped; repository-wide seam/registry audits were performed before CI, and the required executable checks were delegated explicitly to GitHub Actions.
- Because the ordinary PR workflow intentionally does not yet run the Obsidian package checks, temporary workflow-only instrumentation validated the post-review implementation and was then restored byte-for-byte; `.github/workflows/ci.yml` is not part of the final PR diff. On temporary validation run `33949762587`, `npm ci`, plugin lint, typecheck, all 83 plugin tests, build, and `git diff --check` passed. The same temporary run's injected full `pytest -q` produced 2,431 passes plus one expected project-contract failure because `tests/project/test_ci_workflows.py` correctly forbids putting full pytest in the fast PR workflow; this was validation-instrumentation self-detection, not a LIFEOS-1714 regression.
- Clean-head PR `fast-checks` run `33950396658` passed on `0fad54f77862be29fa7f01081fe991a2328bf308`, including task workflow, documentation impact, manual-link validation, Ruff, mypy, Python compilation, test collection, and repository contract smoke tests.
- Clean-head full-validation run `33950434114` passed on `0fad54f77862be29fa7f01081fe991a2328bf308`: all four full pytest shards and aggregate `full-test` succeeded, and `docker-setup-e2e` passed the clean-room setup/MCP gate, home-node service container gate, and ARM64 home-node image build. This clean workflow is the authoritative full-suite result after the temporary instrumentation was removed.
- Normal Codex review found two valid P1 issues: global Obsidian command dispatch namespacing and search focus loss. Both were fixed with regression coverage. Because those fixes materially changed UI behavior, a second review was requested after validation; it confirmed the P1 boundary and found one valid P2 IME-composition edge case, which was fixed locally at the same rendering boundary. All three review threads were replied to and resolved, and no further mechanical review loop was started.
- Security review was skipped under the explicit current-user instruction permitting that review class to be omitted.
- No newly discovered independent product work required a new backlog task. Permanent Obsidian-plugin CI enforcement remains the already-planned LIFEOS-1717 follow-up rather than expanding this feature PR.
- This task-completion move changes only task history metadata/path after the implementation validations above. A fresh current-head `fast-checks` and final `full-validation` checkpoint remain required before merge.
