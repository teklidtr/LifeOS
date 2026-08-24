"""User-facing MCP runtime composed from core and exploration tool surfaces."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.mcp.exploration_tools import build_exploration_tools
from lifeos.mcp.server import (
    LIFEOS_MCP_INSTRUCTIONS as CORE_MCP_INSTRUCTIONS,
    _invoke_mcp_tool,
    create_mcp_server as create_core_mcp_server,
)
from lifeos.registry import Registry
from lifeos.runtime import ActivityStore

LIFEOS_MCP_INSTRUCTIONS = (
    "Exploration is encouraged: use vault_list, vault_search, vault_read_markdown, "
    "vault_read_many, vault_links, wiki_search, and vault_context iteratively to decide what "
    "matters and what to inspect next. Protected retrieval scopes remain default-deny unless "
    "the user explicitly asks to include them. Semantic interpretation belongs to the external "
    "agent. LifeOS constrains mutation, not exploration: canonical changes remain available "
    "only through bounded proposal and consequential authorization tools; there is no generic "
    "vault write, delete, move, or shell surface. "
    + CORE_MCP_INSTRUCTIONS
)


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
) -> FastMCP:
    """Compose the stable core MCP server with read-only exploration primitives."""
    core = create_core_mcp_server(
        vault_root=vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=runtime_dir,
    )
    activity = ActivityStore(runtime_dir or (vault_root / ".lifeos"))
    exploration = build_exploration_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=_invoke_mcp_tool,
    )
    return FastMCP(
        "LifeOS",
        instructions=LIFEOS_MCP_INSTRUCTIONS,
        tools=[*core._tool_manager.list_tools(), *exploration],
    )
