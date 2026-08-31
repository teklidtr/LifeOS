---
id: LIFEOS-1648
title: Align MCP exploration manual with the supported home-node runtime
status: completed
phase: 16
depends_on:
  - LIFEOS-1639
  - LIFEOS-1640
risk: low
---

# Goal

Remove the stale transport statement in the MCP exploration user manual so the documented
exploration/runtime contract matches the already-shipped shared MCP runtime and authenticated
home-node transport.

`docs/user-manual/15-mcp-exploration.md` currently says the supported MCP runtime remains local
STDIO and that a network-accessible/home-node transport is separate future work. That conflicts
with completed LIFEOS-1640 and DD-091, which establish `lifeos serve` authenticated Streamable
HTTP as a supported transport over the same Python MCP/facade core while retaining local STDIO.

# Scope

- Update the transport/deployment section of `docs/user-manual/15-mcp-exploration.md` to describe
  both supported adapters accurately:
  - local `lifeos-mcp` STDIO;
  - authenticated `lifeos serve` Streamable HTTP on the active home node.
- Preserve the shared-core rule: the network adapter does not create a second exploration or
  semantic API.
- State the existing network capability narrowing from DD-091: remote service clients do not
  receive `proposal_approve` or `proposal_apply`, while ordinary policy-filtered exploration and
  guarded proposal-building remain shared.
- Link to the existing setup/home-node workflow instead of duplicating deployment instructions.
- Review neighboring MCP manual wording for direct contradictions with DD-091 and LIFEOS-1640;
  correct only transport-specific drift discovered in that chapter.

# Out of scope

- Changing MCP code, authentication, authorization, networking, deployment, or tool capability
  sets.
- Redesigning the home-node topology or the one-active-writer rule.
- Rewriting unrelated exploration, retrieval, privacy, or ingestion documentation.

# Acceptance criteria

- `docs/user-manual/15-mcp-exploration.md` no longer describes home-node/network MCP as future or
  unsupported work.
- The chapter accurately distinguishes local STDIO from authenticated Streamable HTTP while
  describing both as adapters over the shared LifeOS MCP/business-rule core.
- The existing remote approval/application restriction is stated consistently with DD-091.
- Existing setup/home-node documentation is linked rather than copied.
- No production behavior changes.

# Documentation impact

Status: required

- `docs/user-manual/15-mcp-exploration.md`: replace stale transport guidance with the current
  supported STDIO + authenticated home-node runtime contract.

# Validation

```bash
uv run python scripts/validate_manual_links.py
uv run pytest --import-mode=importlib -q tests/project
```

# Relevant decisions

- DD-079: agent-assisted ingestion is MCP-only.
- DD-087: runtime policy is MCP-owned and exploration/context remain controlled.
- DD-089: one active LifeOS mutation authority remains the cross-device default.
- DD-091: home-node networking is authenticated transport over the shared MCP core.
- LIFEOS-1639: MCP exploration and controlled mutation surface.
- LIFEOS-1640: deployable always-on LifeOS home node.
