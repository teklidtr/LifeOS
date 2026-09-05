---
id: LIFEOS-1712
title: Add user-facing capability registry and bridge API
status: completed
phase: 17
depends_on: []
risk: medium
---

# Goal

Create one Python-owned, machine-readable registry for LifeOS-native user-facing capabilities and expose it through the desktop bridge so Explore and future discovery surfaces can describe what LifeOS actually implements without maintaining a second hard-coded feature catalog.

# Scope

- Add a Python-owned semantic capability registry as application metadata; do not store it in the user vault or derived registry database.
- Define a deterministic capability contract with at least:
  - stable capability ID;
  - human-facing name and description;
  - human-facing category;
  - visibility (`explore` or `internal`);
  - maturity/status metadata such as stable, beta, or experimental;
  - static requirements or setup prerequisites when applicable;
  - backing LifeOS implementation references, including desktop bridge methods and, where needed, named workflows or data sources;
  - user entry points when the capability has a direct UI/workflow destination;
  - optional example prompts only when conversational use is a useful teaching aid.
- Add read-only desktop bridge methods for listing semantic capabilities and retrieving one capability by stable ID.
- Keep semantic capabilities distinct from the existing `system.handshake`/`CAPABILITIES` protocol-method list: the protocol list answers which low-level bridge methods exist, while the new registry answers what user-facing LifeOS abilities those methods compose into.
- Return capability data in deterministic order with a stable serialized shape suitable for the Obsidian plugin.
- Validate duplicate IDs, invalid visibility/status values, malformed backing references, and other registry-shape errors at a central boundary.
- Add unit/bridge tests for registry validation, serialization, list/get behavior, unknown IDs, and deterministic ordering.

# Out of scope

- Cataloging all existing LifeOS features into the registry; that is LIFEOS-1713.
- Building the Obsidian Explore UI; that is LIFEOS-1714.
- Enforcing repository-wide capability coverage in CI; that is LIFEOS-1715.
- Third-party plugins, downloadable extensions, or a marketplace.
- Treating arbitrary prompts that a general LLM can answer as LifeOS capabilities.
- Adding personalized recommendations or dynamic capability ranking.

# Required invariants

- Markdown vault files remain canonical user-owned state; the capability registry is static application metadata, not another source of personal truth.
- The Obsidian plugin does not become the authority for capability definitions.
- A semantic capability represents concrete LifeOS-provided machinery, data access, workflow behavior, or domain behavior; an example prompt by itself is never sufficient to define a capability.
- Removing LifeOS-specific backing behavior must materially change or remove the advertised capability.
- Existing bridge protocol capability negotiation continues to describe low-level supported methods and is not silently repurposed into the semantic catalog.
- Registry reads are side-effect free.

# Acceptance criteria

- Python exposes a single authoritative semantic capability registry with the required metadata and validation.
- The desktop bridge can deterministically list capabilities and retrieve a capability by stable ID.
- Registry serialization clearly distinguishes semantic capability metadata from the existing low-level bridge `CAPABILITIES` method list.
- Duplicate or invalid capability definitions fail deterministic tests rather than being silently accepted.
- Optional example prompts are represented as teaching metadata and are not treated as implementation evidence or auto-executed by the registry API.
- Tests cover the registry model, validation rules, bridge methods, serialization, and unknown-capability behavior.

# Documentation impact

Status: required

- `docs/architecture.md`: document the semantic capability registry boundary and ownership.
- `docs/obsidian-desktop-architecture.md`: document the read-only capability bridge contract and distinguish it from protocol method negotiation.
- `docs/design-decisions.md`: record the durable decision that user-facing capability discovery is Python-owned and semantic capabilities compose lower-level LifeOS methods/workflows rather than duplicating them in the UI.

# Validation commands

- `pytest -q`
- `ruff check .`
- `mypy src/lifeos`
- `git diff --check`

# Relevant design decisions

- DD-037
- DD-101

# Implementation record

- Added the Python-owned semantic capability registry contract, stable schema serialization, deterministic ordering, and fail-closed metadata validation.
- Added read-only `capability.list` and `capability.get` bridge methods while preserving `system.handshake.capabilities` as low-level protocol negotiation.
- Added registry and bridge tests covering validation, malformed runtime shapes, serialization, unknown IDs, deterministic ordering, and side-effect-free reads.
- Updated architecture, desktop architecture, and design decisions; user-facing Explore documentation remains intentionally deferred to LIFEOS-1714.
- The current tool container could not resolve `github.com`, so a repository checkout and the task's local validation commands could not be run there. GitHub Actions was used as the repository validation environment instead.
- PR #52 fast-checks passed on implementation head `369cd4174c628c2ff743a2b57f77b1bedc1bb126`, including task workflow, documentation impact, manual links, Ruff, Mypy, Python compile, test collection, and project contract smoke tests.
- Full validation run `33942626974` passed all four pytest shards (`full-test`) and `docker-setup-e2e`, including clean-room setup, home-node service container, and ARM64 image build gates.
- Codex review on implementation commit `343da1242a539da8af09c0a7e95e0dce84fea8cf` found no major issues. The only later codebase change before validation was a non-material test expectation correction after full pytest exposed a message-match mismatch.
