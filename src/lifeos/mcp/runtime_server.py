"""User-facing MCP runtime composed from core and exploration tool surfaces."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.mcp.exploration_tools import build_exploration_tools, build_policy_read_tools
from lifeos.mcp.server import (
    LIFEOS_MCP_INSTRUCTIONS as CORE_MCP_INSTRUCTIONS,
    _invoke_mcp_tool,
    create_mcp_server as create_core_mcp_server,
)
from lifeos.registry import Registry
from lifeos.runtime import ActivityStore

_POLICY_READ_OVERRIDES = frozenset({"vault_read_markdown", "vault_context", "runtime_activity"})

LIFEOS_MCP_INSTRUCTIONS = (
    "Exploration is encouraged: use vault_list, vault_search, vault_read_markdown, "
    "vault_read_many, vault_links, wiki_search, and vault_context iteratively to decide what "
    "matters and what to inspect next. Protected retrieval scopes remain default-deny and can "
    "cross the MCP boundary only when the user explicitly asks to include them and retrieval "
    "policy permits external disclosure. Runtime activity re-filters path metadata through the "
    "current external policy and never acts as a protected-scope bypass. Semantic interpretation "
    "belongs to the external agent. LifeOS constrains mutation, not exploration: canonical "
    "changes remain available only through bounded proposal and consequential authorization "
    "tools; there is no generic vault write, delete, move, or shell surface. "
    + CORE_MCP_INSTRUCTIONS
)


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
) -> FastMCP:
    """Compose the stable core MCP server with policy-aware exploration primitives."""
    core = create_core_mcp_server(
        vault_root=vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=runtime_dir,
    )
    activity = ActivityStore(runtime_dir or (vault_root / ".lifeos"))
    policy_reads = build_policy_read_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=_invoke_mcp_tool,
    )
    exploration = build_exploration_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=_invoke_mcp_tool,
    )
    core_tools = [
        tool
        for tool in core._tool_manager.list_tools()
        if tool.name not in _POLICY_READ_OVERRIDES
    ]
    return FastMCP(
        "LifeOS",
        instructions=LIFEOS_MCP_INSTRUCTIONS,
        tools=[*core_tools, *policy_reads, *exploration],
    )
