---
id: LIFEOS-1713
title: Inventory and register existing LifeOS capabilities
status: completed
phase: 17
depends_on:
  - LIFEOS-1712
risk: medium
---

# Goal

Build the initial truthful inventory of what LifeOS already provides so Explore can surface existing user-facing capabilities instead of exposing a hand-written or incomplete feature list.

# Scope

- Audit the current repository for already-implemented user-facing behavior using code and authoritative documentation as the source of truth, including:
  - desktop bridge methods and their owning application workflows;
  - Obsidian plugin commands/views;
  - MCP/agent-facing workflows where LifeOS provides concrete data access or behavior;
  - CLI/user workflows documented in `docs/user-manual/`;
  - existing domain features such as planning, reviews, study, retrieval/conversations, experiments, capture, feedback/personal model, and other implemented surfaces found during the audit.
- Add semantic capability definitions for the existing user-facing abilities found by that audit.
- Group low-level methods into human-facing capabilities rather than creating one Explore item per protocol method.
- Use human-facing categories that help discovery; do not mirror Python package names, protocol namespaces, or a universal ontology merely because those structures exist internally.
- For each Explore-visible capability, record the concrete backing bridge methods/workflows/data sources that make it a LifeOS capability.
- Record static setup requirements or prerequisites where the current feature already has them.
- Record a direct entry point when an existing command/view/workflow can open the capability.
- Add optional example prompts only for capabilities where conversational invocation is natural, and ensure each example demonstrates LifeOS-specific data/workflow use rather than generic LLM knowledge.
- Explicitly classify low-level bridge methods that are infrastructure, lifecycle, migration, recovery, or otherwise not independently user-facing as internal/non-Explore so their absence from the catalog is intentional.
- Add tests that validate the baseline inventory against the registry contract, including unique IDs and valid backing references.

# Out of scope

- Implementing missing product functionality discovered during the inventory; record it as separate backlog work instead.
- Building the Explore Obsidian UI; that is LIFEOS-1714.
- Adding CI enforcement for future feature additions; that is LIFEOS-1715.
- Creating capabilities for generic prompts that do not use LifeOS-specific machinery or data.
- Inventing new ontology/entity types solely to organize Explore.
- Third-party extension discovery or installation.

# Required invariants

- The repository, not chat history, determines whether a capability is actually implemented.
- Every Explore-visible item must point to concrete existing LifeOS backing behavior.
- A single semantic capability may compose multiple bridge methods; protocol method count must not determine Explore card count.
- Internal/infrastructure methods remain available to their existing callers even when they are not shown in Explore.
- Capability categories are navigation metadata, not canonical semantic truth about the user's vault.
- The inventory must not claim readiness, integrations, data sources, or workflows that the current implementation does not provide.

# Acceptance criteria

- All currently implemented user-facing feature families identified by the repository audit have corresponding semantic capability entries or an explicit documented reason they should not be Explore-visible.
- Each Explore-visible capability has a stable ID, name, description, category, maturity/status, visibility, and at least one concrete LifeOS backing reference.
- Low-level bridge methods are grouped into meaningful user-facing capabilities rather than mechanically rendered as a protocol list.
- Infrastructure/internal bridge methods encountered during the audit are explicitly classified so omissions are reviewable instead of accidental.
- Example prompts, where present, demonstrate LifeOS-specific behavior and remain optional metadata.
- Tests fail for duplicate IDs, missing required metadata, or references to nonexistent bridge methods.
- The resulting registry is sufficient for a UI to render the current capability catalog without maintaining a second TypeScript feature list.

# Documentation impact

Status: required

- `docs/user-manual/03-feature-breakdown.md`: reconciled the documented feature inventory with the semantic capability catalog, including Explore-visible families, intentional internal groupings, and the current Rich Capture provider-wiring boundary.
- `docs/architecture.md`: reviewed; no edit was required because DD-101 and the LIFEOS-1712 architecture changes already define the mapping rule used by this inventory: semantic capabilities compose existing bridge methods, workflows, and data sources while clients render rather than own a parallel catalog.

# Validation commands

- `pytest -q`
- `ruff check .`
- `mypy src/lifeos`
- `git diff --check`

# Relevant design decisions

- DD-037
- DD-101

# Implementation record

- Audited current desktop bridge methods, Obsidian commands/views, CLI workflows, MCP tools, user-manual feature contracts, architecture, tests, and accepted design decisions rather than relying on chat history.
- Expanded the Python-owned registry to 32 semantic capabilities: 21 Explore-visible user-facing abilities and 11 explicitly internal maintenance/runtime/compatibility groupings.
- Assigned all 148 bridge methods present in the audited protocol snapshot to exactly one semantic capability owner, while deliberately leaving future-change enforcement to LIFEOS-1715.
- Added concrete Obsidian, CLI, MCP, workflow, and data-source references and truthful static prerequisites. Graph and export entries require their existing feature flags; the home-node service declares its configuration, Linux/MCP, actor-ID, and bearer-token startup requirements.
- Kept provider-neutral Rich Capture OCR/transcription/model contracts from being advertised as currently wired provider-backed abilities; the catalog reflects the standard local extraction and existing capture workflow.
- Corrected the semantic registry bridge-method validator to accept underscores already used by current protocol methods such as `daily.task_outcome`.
- Added baseline tests for audited feature families, unique semantic ownership of current bridge references, required metadata, valid backing references, deterministic listing, internal classification, and setup prerequisites.
- Updated `docs/user-manual/03-feature-breakdown.md`; architecture was reviewed and required no duplicate rule beyond the accepted LIFEOS-1712/DD-101 boundary.
- No newly discovered independent implementation work required a new backlog task. The already-planned Explore UI and future discoverability enforcement remain LIFEOS-1714 and LIFEOS-1715.
- A fresh local checkout could not be obtained in the tool container because GitHub DNS resolution failed (`Could not resolve host: github.com`). The closest static/import checks were performed before PR creation, and the unavailable repository validation was explicitly delegated to GitHub Actions.
- PR #53 post-review `fast-checks` run `33946868113` passed on implementation head `f6ffc87684ed2e84ba7f821302a70dca779e7805`, including task workflow, documentation impact, manual-link validation, Ruff, mypy, Python compilation, test collection, and project contract smoke tests.
- The normal Codex review of commit `f41ab40f7a4fd63ffc01bd921dd0d436e6619467` reported two valid P2 prerequisite omissions. Both were fixed on `f6ffc87684ed2e84ba7f821302a70dca779e7805`, covered by regression assertions, replied to, and the outdated review threads were resolved. The fixes did not materially change architecture or runtime behavior, so AGENTS.md did not require a second Codex review.
- Full-validation run `33947630859` passed on implementation head `f6ffc87684ed2e84ba7f821302a70dca779e7805`: all four full pytest shards and aggregate `full-test` succeeded, and `docker-setup-e2e` passed the clean-room setup/MCP gate, home-node service container gate, and ARM64 home-node image build.
- Security review was skipped under the explicit current-user instruction permitting that review class to be omitted.
