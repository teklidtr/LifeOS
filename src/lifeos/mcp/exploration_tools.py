"""MCP adapters for composable, read-only vault exploration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from lifeos.facade.exploration import (
    VAULT_LINKS_DESCRIPTOR,
    VAULT_LIST_DESCRIPTOR,
    VAULT_READ_MANY_DESCRIPTOR,
    VAULT_SEARCH_DESCRIPTOR,
    VaultLinksRequest,
    VaultListRequest,
    VaultReadManyRequest,
    VaultSearchRequest,
    inspect_links,
    list_vault_paths,
    read_many,
    search_vault,
)
from lifeos.mcp.models import (
    VaultLinksMCPResult,
    VaultListMCPResult,
    VaultReadManyMCPResult,
    VaultSearchMCPResult,
)
from lifeos.runtime import ActivityStore

T = TypeVar("T")
Invoke = Callable[[Callable[[], T]], T]

VAULT_LIST_MCP_DESCRIPTION = (
    f"{VAULT_LIST_DESCRIPTOR.description} Use this like a bounded, vault-native find operation. "
    "It returns only canonical Markdown paths/folders allowed by retrieval policy, never host "
    "filesystem paths. Set allow_protected only when the user explicitly asks to include a "
    "protected scope."
)
VAULT_SEARCH_MCP_DESCRIPTION = (
    f"{VAULT_SEARCH_DESCRIPTOR.description} Use this like a bounded vault-native grep before "
    "choosing what to read. It is read-only, policy-aware, and can be narrowed with prefix."
)
VAULT_READ_MANY_MCP_DESCRIPTION = (
    f"{VAULT_READ_MANY_DESCRIPTOR.description} Use this to compare up to eight agent-selected "
    "notes under one total character budget. It is read-only and does not grant mutation authority."
)
VAULT_LINKS_MCP_DESCRIPTION = (
    f"{VAULT_LINKS_DESCRIPTOR.description} Follow current canonical Markdown references in "
    "either direction without shell access. Results are bounded and policy-aware."
)


def _strict_tool(
    fn: Callable[..., object],
    *,
    name: str,
    description: str,
    title: str,
) -> Tool:
    tool = Tool.from_function(
        fn,
        name=name,
        description=description,
        annotations=ToolAnnotations(
            title=title,
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    base_model = tool.fn_metadata.arg_model
    strict_model = cast(
        type[BaseModel],
        type(
            f"Strict{base_model.__name__}",
            (base_model,),
            {
                "model_config": ConfigDict(
                    arbitrary_types_allowed=True,
                    extra="forbid",
                )
            },
        ),
    )
    strict_model.model_rebuild()
    strict_metadata = tool.fn_metadata.model_copy(update={"arg_model": strict_model})
    return tool.model_copy(
        update={
            "fn_metadata": strict_metadata,
            "parameters": strict_model.model_json_schema(by_alias=True),
        }
    )


def build_exploration_tools(
    *,
    vault_root: Path,
    activity: ActivityStore,
    invoke: Invoke[object],
) -> tuple[Tool, ...]:
    """Build the MCP-only adapters over the authoritative exploration facade."""

    def vault_list_tool(
        prefix: str | None = None,
        limit: int = 100,
        allow_protected: bool = False,
    ) -> VaultListMCPResult:
        def op() -> VaultListMCPResult:
            result = list_vault_paths(
                vault_root=vault_root,
                request=VaultListRequest(
                    prefix=prefix,
                    limit=limit,
                    allow_protected=allow_protected,
                ),
            )
            source_paths = [item.path for item in result.entries if item.kind == "file"]
            activity.append(tool="vault_list", source_paths=source_paths)
            return {
                "prefix": result.prefix,
                "entries": [
                    {"path": item.path, "kind": item.kind} for item in result.entries
                ],
                "truncated": result.truncated,
            }

        return cast(VaultListMCPResult, invoke(op))

    def vault_search_tool(
        query: str,
        prefix: str | None = None,
        limit: int = 20,
        allow_protected: bool = False,
    ) -> VaultSearchMCPResult:
        def op() -> VaultSearchMCPResult:
            result = search_vault(
                vault_root=vault_root,
                request=VaultSearchRequest(
                    query=query,
                    prefix=prefix,
                    limit=limit,
                    allow_protected=allow_protected,
                ),
            )
            activity.append(tool="vault_search", source_paths=[item.path for item in result.hits])
            return {
                "query": result.query,
                "hits": [
                    {
                        "path": item.path,
                        "title": item.title,
                        "description": item.description,
                        "excerpt": item.excerpt,
                        "score": item.score,
                        "matched_terms": list(item.matched_terms),
                    }
                    for item in result.hits
                ],
            }

        return cast(VaultSearchMCPResult, invoke(op))

    def vault_read_many_tool(
        paths: list[str],
        max_characters: int = 40_000,
        allow_protected: bool = False,
    ) -> VaultReadManyMCPResult:
        def op() -> VaultReadManyMCPResult:
            result = read_many(
                vault_root=vault_root,
                request=VaultReadManyRequest(
                    paths=tuple(paths),
                    max_characters=max_characters,
                    allow_protected=allow_protected,
                ),
            )
            activity.append(tool="vault_read_many", source_paths=[item.path for item in result.items])
            return {
                "items": [
                    {
                        "path": item.path,
                        "markdown_body": item.markdown_body,
                        "title": item.title,
                        "content_hash": item.content_hash,
                        "truncated": item.truncated,
                    }
                    for item in result.items
                ],
                "total_characters": result.total_characters,
                "truncated": result.truncated,
            }

        return cast(VaultReadManyMCPResult, invoke(op))

    def vault_links_tool(
        path: str,
        direction: str = "both",
        limit: int = 50,
        allow_protected: bool = False,
    ) -> VaultLinksMCPResult:
        def op() -> VaultLinksMCPResult:
            result = inspect_links(
                vault_root=vault_root,
                request=VaultLinksRequest(
                    path=path,
                    direction=cast("object", direction),
                    limit=limit,
                    allow_protected=allow_protected,
                ),
            )
            source_paths = sorted(
                {result.path, *(item.source_path for item in result.links), *(item.target_path for item in result.links)}
            )
            activity.append(tool="vault_links", source_paths=source_paths)
            return {
                "path": result.path,
                "links": [
                    {
                        "source_path": item.source_path,
                        "target_path": item.target_path,
                        "target_heading": item.target_heading,
                        "direction": item.direction,
                    }
                    for item in result.links
                ],
                "truncated": result.truncated,
            }

        return cast(VaultLinksMCPResult, invoke(op))

    return (
        _strict_tool(
            vault_list_tool,
            name="vault_list",
            description=VAULT_LIST_MCP_DESCRIPTION,
            title="Discover vault paths",
        ),
        _strict_tool(
            vault_search_tool,
            name="vault_search",
            description=VAULT_SEARCH_MCP_DESCRIPTION,
            title="Search vault Markdown",
        ),
        _strict_tool(
            vault_read_many_tool,
            name="vault_read_many",
            description=VAULT_READ_MANY_MCP_DESCRIPTION,
            title="Read multiple vault notes",
        ),
        _strict_tool(
            vault_links_tool,
            name="vault_links",
            description=VAULT_LINKS_MCP_DESCRIPTION,
            title="Inspect vault links",
        ),
    )
