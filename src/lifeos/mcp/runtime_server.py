"""User-facing MCP runtime composed from core and exploration tool surfaces."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from lifeos.coherence import CoherenceError
from lifeos.coherence_scoped import runtime_exclusion_prefix
from lifeos.facade.authorization import ConsequentialAuthorizer
from lifeos.facade.errors import ToolExecutionError, ToolValidationError
from lifeos.facade.read_only import WikiSearchRequest, search_wiki
from lifeos.mcp.coherence_tools import build_coherence_tools
from lifeos.mcp.exploration_tools import (
    RUNTIME_ACTIVITY_MCP_DESCRIPTION,
    _activity_path_allowed,
    _strict_tool,
    build_exploration_tools,
    build_policy_read_tools,
)
from lifeos.mcp.models import WikiSearchMCPResult
from lifeos.mcp.server import (
    LIFEOS_MCP_INSTRUCTIONS as CORE_MCP_INSTRUCTIONS,
    WIKI_SEARCH_MCP_DESCRIPTION,
    _invoke_mcp_tool,
    create_mcp_server as create_core_mcp_server,
)
from lifeos.registry import Registry
from lifeos.retrieval import RetrievalError
from lifeos.retrieval.contracts import (
    push_node_local_excluded_prefixes,
    push_node_local_exclusion_predicates,
    reset_node_local_excluded_prefixes,
    reset_node_local_exclusion_predicates,
)
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime import ActivityStore
from lifeos.runtime_scope import build_runtime_exclusion_matcher

_POLICY_READ_OVERRIDES = frozenset(
    {"vault_read_markdown", "wiki_search", "vault_context", "runtime_activity"}
)

LIFEOS_MCP_INSTRUCTIONS = (
    "Exploration is encouraged: use vault_list, vault_search, vault_read_markdown, "
    "vault_read_many, vault_links, wiki_search, vault_context, and vault_note_identity "
    "iteratively to decide what matters and what to inspect next. A canonical note's stable "
    "frontmatter id, current path, and content hash are separate facts; use vault_note_identity "
    "when rename/move continuity matters. Protected retrieval scopes remain default-deny and can "
    "cross the MCP boundary only when the user explicitly asks to include them and retrieval "
    "policy permits external disclosure. Configured node-local runtime state is excluded before "
    "all exploration and context traversal, even when it lives inside the vault. Runtime activity "
    "re-filters path metadata through the current external policy and node-local exclusion and "
    "never acts as a protected-scope bypass. Semantic interpretation belongs to the external "
    "agent. LifeOS constrains mutation, not exploration: canonical changes remain available only "
    "through bounded proposal and consequential authorization tools; there is no generic vault "
    "write, delete, move, or shell surface. "
    + CORE_MCP_INSTRUCTIONS
)


def create_mcp_server(
    *,
    vault_root: Path,
    registry: Registry,
    authorizer: ConsequentialAuthorizer,
    runtime_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    transport_security: TransportSecuritySettings | None = None,
    stateless_http: bool = False,
    json_response: bool = False,
    excluded_core_tools: frozenset[str] = frozenset(),
) -> FastMCP:
    """Compose one MCP tool surface for local STDIO or authenticated network transport."""
    resolved_runtime_dir = runtime_dir or (vault_root / ".lifeos")

    def runtime_scoped_invoke(operation: Callable[[], object]) -> object:
        def scoped_operation() -> object:
            try:
                runtime_prefix = runtime_exclusion_prefix(
                    vault_root,
                    runtime_dir=resolved_runtime_dir,
                )
                matcher = build_runtime_exclusion_matcher(
                    vault_root,
                    runtime_dir=resolved_runtime_dir,
                    snapshot_prefix=runtime_prefix,
                )
            except CoherenceError as error:
                raise ToolExecutionError(
                    "Could not resolve configured runtime directory"
                ) from error

            def runtime_excluded(path: str) -> bool:
                try:
                    return matcher(path)
                except CoherenceError as error:
                    raise ToolExecutionError(
                        "Could not verify configured runtime exclusion"
                    ) from error

            runtime_exclusions = (runtime_prefix,) if runtime_prefix is not None else ()
            prefix_token = push_node_local_excluded_prefixes(runtime_exclusions)
            predicate_token = push_node_local_exclusion_predicates((runtime_excluded,))
            try:
                return operation()
            finally:
                reset_node_local_exclusion_predicates(predicate_token)
                reset_node_local_excluded_prefixes(prefix_token)

        return _invoke_mcp_tool(scoped_operation)

    core = create_core_mcp_server(
        vault_root=vault_root,
        registry=registry,
        authorizer=authorizer,
        runtime_dir=resolved_runtime_dir,
    )
    activity = ActivityStore(resolved_runtime_dir)
    policy_reads = tuple(
        tool
        for tool in build_policy_read_tools(
            vault_root=vault_root,
            activity=activity,
            invoke=runtime_scoped_invoke,
        )
        if tool.name != "runtime_activity"
    )
    exploration = build_exploration_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
    )
    coherence = build_coherence_tools(
        vault_root=vault_root,
        activity=activity,
        invoke=runtime_scoped_invoke,
        runtime_dir=resolved_runtime_dir,
    )

    def wiki_search_tool(query: str, limit: int = 8) -> WikiSearchMCPResult:
        def op() -> WikiSearchMCPResult:
            result = search_wiki(
                vault_root=vault_root,
                request=WikiSearchRequest(query=query, limit=limit),
            )
            activity.append(
                tool="wiki_search",
                source_paths=[hit.path for hit in result.hits],
            )
            return {
                "query": result.query,
                "hits": [
                    {
                        "path": hit.path,
                        "title": hit.title,
                        "description": hit.description,
                        "excerpt": hit.excerpt,
                        "score": hit.score,
                    }
                    for hit in result.hits
                ],
            }

        return cast(WikiSearchMCPResult, runtime_scoped_invoke(op))

    def runtime_activity_tool(limit: int = 20) -> dict[str, object]:
        def op() -> dict[str, object]:
            try:
                records = activity.read(limit=limit)
            except ValueError as exc:
                raise ToolValidationError(str(exc)) from exc
            try:
                load_retrieval_policy(vault_root)
            except RetrievalError as exc:
                raise ToolExecutionError("Retrieval policy is invalid") from exc

            def visible(paths: tuple[str, ...]) -> list[str]:
                return [
                    path
                    for path in paths
                    if _activity_path_allowed(path, vault_root=vault_root)
                ]

            return {
                "records": [
                    {
                        "timestamp": item.timestamp,
                        "tool": item.tool,
                        "actor_id": item.actor_id,
                        "focus_paths": visible(item.focus_paths),
                        "instruction_ids": list(item.instruction_ids),
                        "source_paths": visible(item.source_paths),
                        "proposal_id": item.proposal_id,
                        "target_paths": visible(item.target_paths),
                        "changed_paths": visible(item.changed_paths),
                        "operation_count": item.operation_count,
                    }
                    for item in records
                ]
            }

        return cast(dict[str, object], runtime_scoped_invoke(op))

    wiki_search = _strict_tool(
        wiki_search_tool,
        name="wiki_search",
        description=WIKI_SEARCH_MCP_DESCRIPTION,
        title="Search durable wiki",
    )
    runtime_activity = _strict_tool(
        runtime_activity_tool,
        name="runtime_activity",
        description=RUNTIME_ACTIVITY_MCP_DESCRIPTION,
        title="Read runtime activity",
    )
    core_tools = [
        tool
        for tool in core._tool_manager.list_tools()
        if tool.name not in _POLICY_READ_OVERRIDES and tool.name not in excluded_core_tools
    ]
    return FastMCP(
        "LifeOS",
        instructions=LIFEOS_MCP_INSTRUCTIONS,
        tools=[
            *core_tools,
            *policy_reads,
            *exploration,
            wiki_search,
            runtime_activity,
            *coherence,
        ],
        host=host,
        port=port,
        transport_security=transport_security,
        stateless_http=stateless_http,
        json_response=json_response,
    )
