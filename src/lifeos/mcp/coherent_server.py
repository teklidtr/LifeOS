"""Coherence-aware wrapper for the core MCP server."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.facade.registry_tools import refresh_registry
from lifeos.mcp import server as _server
from lifeos.mcp.models import RegistryRefreshMCPResult
from lifeos.registry import Registry
from lifeos.runtime import ActivityStore

_ORIGINAL_CREATE_MCP_SERVER = _server.create_mcp_server


def _changed_paths_with_renames(
    *,
    new: tuple[str, ...],
    modified: tuple[str, ...],
    deleted: tuple[str, ...],
    renamed: tuple[tuple[str, str], ...],
) -> list[str]:
    paths = [*new, *modified, *deleted]
    for old_path, new_path in renamed:
        paths.extend((old_path, new_path))
    return list(dict.fromkeys(paths))


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
) -> FastMCP:
    """Build the core MCP surface while retaining rename evidence from registry refreshes."""
    core = _ORIGINAL_CREATE_MCP_SERVER(
        vault_root=vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=runtime_dir,
    )
    activity = ActivityStore(runtime_dir or (vault_root / ".lifeos"))

    def registry_refresh_tool() -> RegistryRefreshMCPResult:
        def op() -> RegistryRefreshMCPResult:
            result = refresh_registry(vault_root=vault_root, registry=registry)
            activity.append(
                tool="registry_refresh",
                changed_paths=_changed_paths_with_renames(
                    new=result.new,
                    modified=result.modified,
                    deleted=result.deleted,
                    renamed=result.renamed,
                ),
            )
            return {
                "new": list(result.new),
                "modified": list(result.modified),
                "unchanged": list(result.unchanged),
                "deleted": list(result.deleted),
                "renamed": [
                    {"from_path": old_path, "to_path": new_path}
                    for old_path, new_path in result.renamed
                ],
                "proposals_indexed": result.proposals_indexed,
            }

        return _server._invoke_mcp_tool(op)

    replacement = _server._strict_tool(
        registry_refresh_tool,
        name="registry_refresh",
        description=_server.REGISTRY_REFRESH_MCP_DESCRIPTION,
        annotations=ToolAnnotations(
            title="Refresh LifeOS registry",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    tools = [
        replacement if tool.name == "registry_refresh" else tool
        for tool in core._tool_manager.list_tools()
    ]
    return FastMCP(
        "LifeOS",
        instructions=_server.LIFEOS_MCP_INSTRUCTIONS,
        tools=tools,
    )
