---
id: LIFEOS-1713
title: Inventory and register existing LifeOS capabilities
status: in-progress
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

- `docs/user-manual/03-feature-breakdown.md`: reconcile the documented feature inventory with the semantic capability catalog and remove or call out any discrepancy discovered during the audit.
- `docs/architecture.md`: document how existing implementation surfaces map into semantic capabilities if the inventory reveals mapping rules not already captured by LIFEOS-1712.

# Validation commands

- `pytest -q`
- `ruff check .`
- `mypy src/lifeos`
- `git diff --check`

# Relevant design decisions

- DD-037
