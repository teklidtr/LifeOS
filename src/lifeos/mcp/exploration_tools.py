"""MCP adapters for composable, read-only vault exploration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeVar, cast

from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from lifeos.facade.errors import ToolExecutionError, ToolValidationError
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
from lifeos.facade.read_only import (
    READ_MARKDOWN_DESCRIPTOR,
    VAULT_CONTEXT_DESCRIPTOR,
    ReadMarkdownRequest,
    VaultContextRequest,
    get_vault_context,
    read_markdown,
)
from lifeos.mcp.models import (
    ReadMarkdownMCPResult,
    RuntimeActivityMCPResult,
    VaultContextMCPResult,
    VaultLinksMCPResult,
    VaultListMCPResult,
    VaultReadManyMCPResult,
    VaultSearchMCPResult,
)
from lifeos.retrieval import RetrievalError, RetrievalScope, scope_decision
from lifeos.retrieval.policy import load_retrieval_policy
from lifeos.runtime import ActivityStore

Invoke = Callable[[Callable[[], object]], object]
RequestT = TypeVar("RequestT")

VAULT_LIST_MCP_DESCRIPTION = (
    f"{VAULT_LIST_DESCRIPTOR.description} Use this like a bounded, vault-native find operation. "
    "It returns only canonical Markdown paths/folders allowed for external disclosure by "
    "retrieval policy, never host filesystem paths. Continue a truncated listing with "
    "next_after. Set allow_protected only when the user explicitly asks to include a protected "
    "scope; protected content must also be externally allowlisted by policy."
)
VAULT_SEARCH_MCP_DESCRIPTION = (
    f"{VAULT_SEARCH_DESCRIPTOR.description} Use this like a bounded vault-native grep before "
    "choosing what to read. It is read-only, filtered for external disclosure by retrieval "
    "policy, can be narrowed with prefix, and reports parser omissions in diagnostics. Search "
    "titles and descriptions are separately bounded."
)
VAULT_READ_MANY_MCP_DESCRIPTION = (
    f"{VAULT_READ_MANY_DESCRIPTOR.description} Use this to compare up to eight agent-selected "
    "notes under one Markdown-body character budget with separately bounded metadata. It is "
    "read-only and does not grant mutation authority."
)
VAULT_LINKS_MCP_DESCRIPTION = (
    f"{VAULT_LINKS_DESCRIPTOR.description} Follow current canonical Markdown references in "
    "either direction without shell access. Markdown links remain source-relative; basename "
    "wikilinks are resolved only when unique. Continue truncated results with next_offset. "
    "Allowed backlink sources that cannot be read or parsed are reported in bounded diagnostics."
)
READ_MARKDOWN_MCP_DESCRIPTION = (
    f"{READ_MARKDOWN_DESCRIPTOR.description} This runtime read is filtered for external "
    "disclosure by retrieval policy. Set allow_protected only when the user explicitly asks to "
    "include a protected scope; the path must also be externally allowlisted by policy."
)
VAULT_CONTEXT_MCP_DESCRIPTION = (
    f"{VAULT_CONTEXT_DESCRIPTOR.description} Focused, lexical, and instruction sources are "
    "filtered for external disclosure by retrieval policy before content access. Set "
    "allow_protected only when the user explicitly asks to include a protected scope and policy "
    "also permits external disclosure."
)
RUNTIME_ACTIVITY_MCP_DESCRIPTION = (
    "Read recent disposable MCP routing/activity metadata for debugging. Path fields are "
    "re-filtered through the current external retrieval policy, so protected or excluded path "
    "names are not disclosed by a later activity read."
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
                    strict=True,
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


def _validated_request(factory: Callable[[], RequestT]) -> RequestT:
    try:
        return factory()
    except ValueError as exc:
        raise ToolValidationError(str(exc)) from exc


def _activity_path_allowed(path: str, *, vault_root: Path) -> bool:
    try:
        policy = load_retrieval_policy(vault_root)
        return scope_decision(
            path,
            scope=RetrievalScope(),
            policy=policy,
            mode="external",
        ).allowed
    except RetrievalError:
        return False


def build_policy_read_tools(
    *,
    vault_root: Path,
    activity: ActivityStore,
    invoke: Invoke,
) -> tuple[Tool, ...]:
    """Build policy-aware replacements for legacy composed read tools."""

    def vault_read_markdown_tool(
        vault_path: str,
        allow_protected: bool = False,
    ) -> ReadMarkdownMCPResult:
        def op() -> ReadMarkdownMCPResult:
            request = _validated_request(
                lambda: ReadMarkdownRequest(
                    vault_path=vault_path,
                    allow_protected=allow_protected,
                    mode="external",
                )
            )
            result = read_markdown(vault_root=vault_root, request=request)
            activity.append(tool="vault_read_markdown", source_paths=[result.vault_path])
            return {
                "vault_path": result.vault_path,
                "markdown_body": result.markdown_body,
                "source_tags": list(result.source_tags),
                "source_topics": list(result.source_topics),
            }

        return cast(ReadMarkdownMCPResult, invoke(op))

    def vault_context_tool(
        question: str,
        focus_paths: list[str] | None = None,
        limit: int = 8,
        allow_protected: bool = False,
    ) -> VaultContextMCPResult:
        def op() -> VaultContextMCPResult:
            request = _validated_request(
                lambda: VaultContextRequest(
                    question=question,
                    focus_paths=tuple(focus_paths or ()),
                    limit=limit,
                    allow_protected=allow_protected,
                    mode="external",
                )
            )
            pack = get_vault_context(vault_root=vault_root, request=request)
            activity.append(
                tool="vault_context",
                focus_paths=list(focus_paths or ()),
                instruction_ids=[item.id for item in pack.instructions],
                source_paths=[item.path for item in pack.sources],
            )
            return {
                "question": pack.question,
                "instructions": [
                    {
                        "id": item.id,
                        "text": item.text,
                        "authority": item.authority,
                        "scope": item.scope,
                        "priority": item.priority,
                        "applicable_sources": list(item.applicable_sources),
                        "applicability": list(item.applicability),
                    }
                    for item in pack.instructions
                ],
                "sources": [
                    {
                        "path": item.path,
                        "title": item.title,
                        "description": item.description,
                        "excerpt": item.excerpt,
                        "score": item.score,
                    }
                    for item in pack.sources
                ],
                "evidence_gaps": list(pack.evidence_gaps),
                "omissions": list(pack.omissions),
                "diagnostics": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "source_path": item.source_path,
                        "line": item.line,
                        "message": item.message,
                    }
                    for item in pack.diagnostics
                ],
            }

        return cast(VaultContextMCPResult, invoke(op))

    def runtime_activity_tool(limit: int = 20) -> RuntimeActivityMCPResult:
        def op() -> RuntimeActivityMCPResult:
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

        return cast(RuntimeActivityMCPResult, invoke(op))

    return (
        _strict_tool(
            vault_read_markdown_tool,
            name="vault_read_markdown",
            description=READ_MARKDOWN_MCP_DESCRIPTION,
            title="Read vault Markdown",
        ),
        _strict_tool(
            vault_context_tool,
            name="vault_context",
            description=VAULT_CONTEXT_MCP_DESCRIPTION,
            title="Build vault context",
        ),
        _strict_tool(
            runtime_activity_tool,
            name="runtime_activity",
            description=RUNTIME_ACTIVITY_MCP_DESCRIPTION,
            title="Read runtime activity",
        ),
    )


def build_exploration_tools(
    *,
    vault_root: Path,
    activity: ActivityStore,
    invoke: Invoke,
) -> tuple[Tool, ...]:
    """Build the MCP-only adapters over the authoritative exploration facade."""

    def vault_list_tool(
        prefix: str | None = None,
        limit: int = 100,
        allow_protected: bool = False,
        after: str | None = None,
    ) -> VaultListMCPResult:
        def op() -> VaultListMCPResult:
            request = _validated_request(
                lambda: VaultListRequest(
                    prefix=prefix,
                    limit=limit,
                    allow_protected=allow_protected,
                    after=after,
                    mode="external",
                )
            )
            result = list_vault_paths(vault_root=vault_root, request=request)
            source_paths = [item.path for item in result.entries if item.kind == "file"]
            activity.append(tool="vault_list", source_paths=source_paths)
            return {
                "prefix": result.prefix,
                "entries": [
                    {"path": item.path, "kind": item.kind} for item in result.entries
                ],
                "truncated": result.truncated,
                "next_after": result.next_after,
            }

        return cast(VaultListMCPResult, invoke(op))

    def vault_search_tool(
        query: str,
        prefix: str | None = None,
        limit: int = 20,
        allow_protected: bool = False,
    ) -> VaultSearchMCPResult:
        def op() -> VaultSearchMCPResult:
            request = _validated_request(
                lambda: VaultSearchRequest(
                    query=query,
                    prefix=prefix,
                    limit=limit,
                    allow_protected=allow_protected,
                    mode="external",
                )
            )
            result = search_vault(vault_root=vault_root, request=request)
            activity.append(
                tool="vault_search",
                source_paths=[item.path for item in result.hits],
            )
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
                "diagnostics": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "source_path": item.source_path,
                        "line": item.line,
                        "message": item.message,
                    }
                    for item in result.diagnostics
                ],
            }

        return cast(VaultSearchMCPResult, invoke(op))

    def vault_read_many_tool(
        paths: list[str],
        max_characters: int = 40_000,
        allow_protected: bool = False,
    ) -> VaultReadManyMCPResult:
        def op() -> VaultReadManyMCPResult:
            request = _validated_request(
                lambda: VaultReadManyRequest(
                    paths=tuple(paths),
                    max_characters=max_characters,
                    allow_protected=allow_protected,
                    mode="external",
                )
            )
            result = read_many(vault_root=vault_root, request=request)
            activity.append(
                tool="vault_read_many",
                source_paths=[item.path for item in result.items],
            )
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
        direction: Literal["outgoing", "backlinks", "both"] = "both",
        limit: int = 50,
        allow_protected: bool = False,
        offset: int = 0,
    ) -> VaultLinksMCPResult:
        def op() -> VaultLinksMCPResult:
            request = _validated_request(
                lambda: VaultLinksRequest(
                    path=path,
                    direction=direction,
                    limit=limit,
                    allow_protected=allow_protected,
                    offset=offset,
                    mode="external",
                )
            )
            result = inspect_links(vault_root=vault_root, request=request)
            source_paths = sorted(
                {
                    result.path,
                    *(item.source_path for item in result.links),
                    *(item.target_path for item in result.links),
                }
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
                "next_offset": result.next_offset,
                "diagnostics": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "source_path": item.source_path,
                        "line": item.line,
                        "message": item.message,
                    }
                    for item in result.diagnostics
                ],
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
