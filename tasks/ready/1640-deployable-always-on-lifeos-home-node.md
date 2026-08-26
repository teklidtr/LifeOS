---
id: LIFEOS-1640
title: Add deployable always-on LifeOS home node
status: ready
phase: 16
depends_on:
  - LIFEOS-1639
  - LIFEOS-1643
risk: high
---

# Goal

Make LifeOS runnable as a long-lived, always-on home node on hardware such as Home Assistant
Yellow, a NAS, mini PC, Raspberry Pi-class Linux host, or other container-capable server so
agents on phones, laptops, and tablets can use the same LifeOS/vault without requiring the
agent device to hold a local vault copy or keep a personal computer running.

The home node must host LifeOS deterministic operations and have filesystem access to the
selected vault. Agent intelligence remains external. Existing local STDIO MCP usage must
continue to work alongside the new deployment mode.

# Design principles

- Separate deployment/transport from LifeOS core business rules.
- Keep local STDIO MCP as a supported first-class mode.
- Add an explicit long-lived service mode rather than changing `lifeos init` into a daemon
  installer or client configurator.
- The node may own, mount, or receive a synchronized vault copy according to the authoritative
  topology/coherence contract from LIFEOS-1643; LifeOS does not require the user's agent device
  to store the vault.
- Agent semantic reasoning stays in Codex/ChatGPT/Claude/other external agents. The node
  performs deterministic LifeOS tools, validation, authorization, proposal lifecycle,
  registry/index work, and vault I/O.
- Remote access must fail closed and must not create an unauthenticated public vault API.
- Prefer portable Linux/container deployment with ARM64 support so Home Assistant Yellow is
  a realistic target without coupling LifeOS core to Home Assistant.

# Scope

- Define the durable runtime boundary for an always-on LifeOS node:

  ```text
  remote agent/client
          |
      secure MCP/network transport
          |
      LifeOS service
          |
      LifeOS core
          |
   vault + Git + rebuildable runtime state
  ```

- Add a supported long-lived server/service entry point, tentatively `lifeos serve`, or an
  equivalently explicit command chosen during implementation.
- Reuse the same authoritative MCP tool/facade/business-rule surface used by local STDIO
  rather than creating a second remote API implementation.
- Select and implement a supported network-capable MCP transport or thin gateway compatible
  with the maintained MCP SDK, with explicit authentication and stable actor identity.
- Define safe bind defaults, authentication configuration, secret handling, connection
  logging, request/error boundaries, and guidance for TLS/private-network exposure.
- Do not expose the service to the public Internet unauthenticated. Document supported safe
  access patterns such as a private LAN/VPN overlay or authenticated TLS reverse proxy.
- Preserve `--actor-id`/actor attribution semantics across remote requests so ownership,
  proposal, provenance, and activity records remain attributable.
- Add health/readiness behavior suitable for service managers and containers, composing
  existing deterministic doctor/status checks where appropriate rather than duplicating
  them.
- Add container/service packaging suitable for an always-on Linux host, including ARM64.
- Validate vault mounting/persistence, Git availability, restart behavior, rebuildable
  SQLite/runtime state, and non-destructive startup.
- Define a Home Assistant Yellow deployment path. Prefer a generic OCI/container artifact;
  where Home Assistant OS requires platform packaging, provide or specify the thinnest
  Home Assistant App/add-on wrapper needed without moving Home Assistant concerns into
  LifeOS core.
- Implement/document the vault placement or synchronization topology selected by LIFEOS-1643;
  the node must satisfy that coherence contract before it performs LifeOS operations.
- Add integration coverage proving that a remote client with no local vault can perform the
  MCP-only exploratory flow from LIFEOS-1639 and create a guarded proposal through the
  home node.

# Out of scope

- Embedding an LLM/provider runtime, API keys, or autonomous agent brain inside LifeOS.
- Replacing Obsidian Sync or building a general-purpose cross-device file synchronization
  product as part of this task.
- Automatically changing Codex, Claude, ChatGPT, Obsidian, shell, router, VPN, DNS, or Home
  Assistant client configuration from `lifeos init`.
- Requiring the canonical vault to move permanently off the user's computer; mounted or
  synchronized deployment models remain valid when they satisfy LIFEOS-1643 coherence rules.
- Granting remote agents unrestricted host shell access.
- Supporting arbitrary unauthenticated WAN exposure.
- Running large local language models on Home Assistant Yellow.

# Acceptance criteria

- LifeOS can run as a long-lived service independently of a Codex/Claude process spawning
  `lifeos-mcp` over STDIO.
- Existing local STDIO `lifeos-mcp` remains supported and uses the same LifeOS core contracts
  as the service mode.
- A remote MCP/client process with no local vault copy can authenticate to the node, retain
  stable actor identity, use the LIFEOS-1639 exploration surface, and submit a proposal.
- Remote mutation cannot bypass the same ownership, provenance, proposal, lifecycle, and
  authorization rules enforced locally.
- The service refuses or degrades safely when the configured vault does not satisfy the
  LIFEOS-1643 authoritative topology/coherence assumptions required for mutation.
- Default service configuration does not create an unauthenticated publicly reachable vault
  endpoint; insecure exposure requires neither hidden defaults nor accidental wildcard
  binding.
- Authentication secrets are not stored in canonical Markdown, emitted in normal activity
  logs, or returned by diagnostic surfaces.
- A supported Linux/container deployment survives restart with canonical vault/Git state
  intact and can rebuild disposable runtime state when required.
- ARM64 deployment is validated sufficiently for Raspberry Pi-class hardware, and the docs
  include a concrete Home Assistant Yellow path or clearly identified thin platform wrapper
  when Home Assistant OS packaging is required.
- `lifeos init` remains vault bootstrap only and does not install/start the service or edit
  external client configuration.
- Health/readiness diagnostics are deterministic and suitable for container/service
  supervision.
- Normal CI, Docker clean-room setup, and real MCP integration gates remain green, with new
  network/service integration coverage added without an LLM in the loop.

# Documentation impact

Status: required

- `docs/architecture.md`: define local STDIO versus long-lived home-node deployment and the
  transport/core/vault responsibility boundary.
- `docs/user-manual/04-setup-and-installation.md`: document server installation, persistent
  vault/runtime storage, authentication, ARM64, and Home Assistant Yellow deployment.
- `docs/user-manual/05-workflow.md`: document remote phone/laptop agent workflows and explain
  that the client device does not need a local vault copy.
- `README.md`: add the supported home-node/service mode once shipped, while preserving local
  quick-start guidance.
- Add dedicated operational/security documentation if authentication, TLS, VPN/reverse-proxy,
  backup, or service-manager guidance is too large for the setup chapter.

# Validation

```bash
uv run pytest --import-mode=importlib -q tests/mcp tests/integration
uv run pytest --import-mode=importlib -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
uv run python scripts/validate_manual_links.py
./scripts/run-setup-integration-docker.sh
# Add container/network integration commands for the selected service transport and ARM64 artifact.
```

# Relevant decisions

- LIFEOS-1639 defines the MCP exploration-versus-mutation surface required for a useful
  vault-less remote client.
- LIFEOS-1643 defines the cross-device vault topology and writer/coherence contract that the
  home node must satisfy rather than inventing sync semantics inside deployment code.
- DD-033: SQLite/runtime-derived state remains disposable and rebuildable; persistent node
  deployment must not make it canonical.
- DD-035: generated ownership remains canonical authorization data and must fail closed
  remotely as it does locally.
- DD-036: Python remains the sole business-rule engine across STDIO and network transports.
- DD-087: service/network integration tests remain deterministic infrastructure tests without
  an LLM in the loop.
- DD-088: `lifeos init` remains first-party, deterministic, non-destructive vault bootstrap
  and never mutates external client configuration.
- A new durable design decision should be added if implementation establishes a network
  authentication, service-lifecycle, or remote-deployment contract not already covered by
  authoritative architecture decisions.
