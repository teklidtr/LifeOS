---
id: LIFEOS-1714
title: Build Explore capability browser in Obsidian
status: backlog
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
